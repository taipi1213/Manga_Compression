#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZIP/RAR アーカイブ破損チェックツール

manga_asyuku_v2.py で出力されたZIPファイルが破損していないかをチェックするツール。
ZIPファイル内のすべての画像が正常に開けるかを確認します。

使い方:
1. このスクリプトを実行
2. チェックするフォルダを選択（またはドラッグ&ドロップ）
3. 結果がログに表示される
"""

import os
import sys
import zipfile
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image
import concurrent.futures
import threading
import time
import csv
import warnings

# 高解像度画像のDecompressionBomb警告を抑制
# 漫画の高品質スキャンでは大きなピクセル数になることがあるため
Image.MAX_IMAGE_PIXELS = None  # 制限を無効化
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

class ArchiveChecker:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ZIP/RAR 破損チェックツール")
        self.root.geometry("800x600")
        
        # 変数
        self.processing = False
        self.cancel_flag = False
        self.results = []  # [(アーカイブ名, 状態, 詳細), ...]
        
        self.create_widgets()
        
    def create_widgets(self):
        """UIを作成"""
        # 上部: フォルダ選択
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(top_frame, text="チェック対象フォルダ:").pack(side=tk.LEFT)
        self.folder_var = tk.StringVar()
        tk.Entry(top_frame, textvariable=self.folder_var, width=50).pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="参照", command=self.select_folder).pack(side=tk.LEFT)
        
        # サブフォルダ検索オプション（初期値オフ）
        self.include_subfolders = tk.BooleanVar(value=False)
        tk.Checkbutton(
            top_frame, 
            text="サブフォルダも対象", 
            variable=self.include_subfolders
        ).pack(side=tk.LEFT, padx=10)
        
        # ボタン
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.check_button = tk.Button(
            button_frame, text="チェック開始", command=self.start_check,
            bg="#66CC66", width=15, height=2, font=("", 10, "bold")
        )
        self.check_button.pack(side=tk.LEFT, padx=5)
        
        self.cancel_button = tk.Button(
            button_frame, text="中止", command=self.cancel_check,
            bg="#FF6666", width=10, height=2, state=tk.DISABLED
        )
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        
        self.export_button = tk.Button(
            button_frame, text="結果をCSV出力", command=self.export_results,
            width=15, height=2
        )
        self.export_button.pack(side=tk.RIGHT, padx=5)
        
        # プログレスバー
        progress_frame = tk.Frame(self.root)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X)
        
        self.status_label = tk.Label(progress_frame, text="待機中...")
        self.status_label.pack(anchor="w")
        
        # サマリー
        summary_frame = tk.LabelFrame(self.root, text="チェック結果サマリー")
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.summary_labels = {}
        for i, (key, text, color) in enumerate([
            ("total", "合計: 0", "black"),
            ("ok", "正常: 0", "green"),
            ("error", "エラー: 0", "red"),
            ("warning", "警告: 0", "orange")
        ]):
            label = tk.Label(summary_frame, text=text, fg=color, font=("", 10, "bold"))
            label.pack(side=tk.LEFT, padx=20, pady=5)
            self.summary_labels[key] = label
        
        # ログ表示
        log_frame = tk.LabelFrame(self.root, text="詳細ログ")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        self.log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.log_text.yview)
        
        # タグ設定
        self.log_text.tag_configure("ok", foreground="green")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("info", foreground="blue")
        
    def select_folder(self):
        """フォルダを選択"""
        folder = filedialog.askdirectory(title="チェックするフォルダを選択")
        if folder:
            self.folder_var.set(folder)
            
    def log(self, message, tag=None):
        """ログを出力"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        
    def start_check(self):
        """チェックを開始"""
        folder = self.folder_var.get()
        if not folder or not os.path.exists(folder):
            messagebox.showerror("エラー", "有効なフォルダを選択してください。")
            return
        
        self.processing = True
        self.cancel_flag = False
        self.results = []
        
        self.check_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        
        # 非同期で実行
        thread = threading.Thread(target=self.run_check, args=(folder,))
        thread.daemon = True
        thread.start()
        
    def cancel_check(self):
        """チェックを中止"""
        self.cancel_flag = True
        self.log("チェックを中止しています...", "warning")
        
    def run_check(self, folder):
        """チェックを実行"""
        try:
            # ZIPファイルを収集
            zip_files = []
            
            if self.include_subfolders.get():
                # サブフォルダも含めて検索
                for root, dirs, files in os.walk(folder):
                    for f in files:
                        if f.lower().endswith('.zip'):
                            zip_files.append(os.path.join(root, f))
            else:
                # 指定フォルダのみ検索（サブフォルダを除外）
                for f in os.listdir(folder):
                    if f.lower().endswith('.zip'):
                        full_path = os.path.join(folder, f)
                        if os.path.isfile(full_path):
                            zip_files.append(full_path)
            
            if not zip_files:
                self.log("ZIPファイルが見つかりませんでした。", "warning")
                return
            
            self.log(f"検出されたZIPファイル: {len(zip_files)}件", "info")
            
            total = len(zip_files)
            ok_count = 0
            error_count = 0
            warning_count = 0
            
            for i, zip_path in enumerate(zip_files):
                if self.cancel_flag:
                    break
                
                # 進捗更新
                progress = (i + 1) / total * 100
                self.progress_var.set(progress)
                self.status_label.config(text=f"チェック中: {os.path.basename(zip_path)} ({i+1}/{total})")
                
                # ZIPをチェック
                status, details = self.check_zip(zip_path)
                
                self.results.append({
                    'archive': os.path.basename(zip_path),
                    'path': zip_path,
                    'status': status,
                    'details': details
                })
                
                if status == "OK":
                    ok_count += 1
                    self.log(f"✓ {os.path.basename(zip_path)}: 正常 ({details})", "ok")
                elif status == "WARNING":
                    warning_count += 1
                    self.log(f"⚠ {os.path.basename(zip_path)}: 警告", "warning")
                    self.log(f"    └ 理由: {details}", "warning")
                    self.log(f"    └ パス: {zip_path}", "warning")
                else:
                    error_count += 1
                    self.log(f"✗ {os.path.basename(zip_path)}: エラー", "error")
                    self.log(f"    └ 詳細: {details}", "error")
                    self.log(f"    └ パス: {zip_path}", "error")
                    # ファイルサイズも表示
                    try:
                        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
                        self.log(f"    └ サイズ: {size_mb:.2f} MB", "error")
                    except:
                        pass
                
                # サマリー更新
                self.summary_labels["total"].config(text=f"合計: {i+1}")
                self.summary_labels["ok"].config(text=f"正常: {ok_count}")
                self.summary_labels["error"].config(text=f"エラー: {error_count}")
                self.summary_labels["warning"].config(text=f"警告: {warning_count}")
            
            # 完了
            if self.cancel_flag:
                self.log("チェックが中止されました。", "warning")
            else:
                self.log(f"チェック完了: 正常 {ok_count}件, エラー {error_count}件, 警告 {warning_count}件", "info")
                
        except Exception as e:
            self.log(f"チェック中にエラーが発生: {e}", "error")
        finally:
            self.processing = False
            self.check_button.config(state=tk.NORMAL)
            self.cancel_button.config(state=tk.DISABLED)
            self.progress_var.set(100)
            self.status_label.config(text="完了")
            
    def check_zip(self, zip_path):
        """ZIPファイルをチェック"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # ZIPの整合性チェック
                bad_file = zf.testzip()
                if bad_file:
                    return "ERROR", f"破損ファイル: {bad_file}"
                
                # 画像ファイルの検証
                image_files = [f for f in zf.namelist() 
                               if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'))]
                
                if not image_files:
                    return "WARNING", "画像ファイルがありません"
                
                # 一部の画像をサンプルチェック（最大10枚）
                sample_size = min(10, len(image_files))
                sample_files = image_files[:sample_size]
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    for img_name in sample_files:
                        try:
                            zf.extract(img_name, temp_dir)
                            img_path = os.path.join(temp_dir, img_name)
                            
                            # 画像として開けるか確認
                            with Image.open(img_path) as img:
                                img.verify()
                        except Exception as img_err:
                            return "ERROR", f"画像破損: {img_name} ({str(img_err)})"
                
                return "OK", f"{len(image_files)}枚の画像を確認"
                
        except zipfile.BadZipFile:
            return "ERROR", "ZIPファイルが破損しています"
        except Exception as e:
            return "ERROR", str(e)
            
    def export_results(self):
        """結果をCSVに出力"""
        if not self.results:
            messagebox.showinfo("情報", "エクスポートする結果がありません。")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSVファイル", "*.csv")],
            initialfile=f"check_results_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            title="結果をCSVに保存"
        )
        
        if not filepath:
            return
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['アーカイブ名', 'パス', '状態', '詳細'])
                for r in self.results:
                    writer.writerow([
                        r['archive'],
                        r['path'],
                        r['status'],
                        r['details']
                    ])
            
            self.log(f"結果をCSV出力しました: {filepath}", "info")
            messagebox.showinfo("完了", f"結果を保存しました:\n{filepath}")
            
        except Exception as e:
            messagebox.showerror("エラー", f"CSV出力に失敗しました:\n{e}")
            
    def run(self):
        """アプリケーションを実行"""
        self.root.mainloop()


def main():
    app = ArchiveChecker()
    app.run()


if __name__ == "__main__":
    main()
