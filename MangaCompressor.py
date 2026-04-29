import os
import zipfile
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Menu
from PIL import Image, ImageTk
import concurrent.futures
import queue
import json
import sys
import locale
import logging
from functools import partial
import time
import psutil
import atexit
from tkinter import simpledialog, messagebox
import datetime
import winsound  # Windows標準音の再生に使用

# ロギング設定
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    filename='caesium_gui.log')
logger = logging.getLogger('CaesiumGUI')

# 依存関係のチェック
DEPENDENCIES = {
    "tkinterdnd2": "pip install tkinterdnd2",
    "send2trash": "pip install send2trash"  # 追加：ゴミ箱機能用
}

try:

    # Pillowのインポートを試みる
    try:
        from PIL import Image, ImageTk
    except ImportError:
        print("PIL がインストールされていません。'pip install Pillow' を実行してください。")
        sys.exit(1)

    # その他の依存関係チェック
    for module, install_cmd in DEPENDENCIES.items():
        try:
            __import__(module)
        except ImportError:
            print(f"{module} がインストールされていません。\n{install_cmd} を実行してください。")
            sys.exit(1)
except Exception as e:
    print(f"エラー: {e}")
    sys.exit(1)

# 正常にインポートできる場合のみ実行
from tkinterdnd2 import DND_FILES, TkinterDnD
import send2trash  # ゴミ箱機能用

# クラス外に圧縮処理用の関数を定義（ProcessPoolExecutor用）
def compress_image_worker(src_path, dst_folder, jpeg_quality, jpeg_progressive, jpeg_keep_metadata,
                         png_compression_level, png_keep_metadata, webp_quality, webp_keep_metadata,
                         tiff_keep_metadata, resize_mode, resize_width, resize_height, resize_modes,
                         skip_if_larger, file_suffix, temp_files=None, pause_callback=None, base_folder=None):
    try:
        dst_dir = dst_folder
        if base_folder:
            try:
                src_abs = os.path.abspath(src_path)
                base_abs = os.path.abspath(base_folder)
                if os.path.commonpath([src_abs, base_abs]) == base_abs:
                    rel_dir = os.path.dirname(os.path.relpath(src_abs, base_abs))
                    if rel_dir and rel_dir != ".":
                        dst_dir = os.path.join(dst_folder, rel_dir)
            except Exception:
                dst_dir = dst_folder
        os.makedirs(dst_dir, exist_ok=True)

        # 一時停止チェック
        if pause_callback and pause_callback():
            while pause_callback():
                time.sleep(0.1)  # 一時停止中は待機
                
        # リサイズ処理
        resized_path = maybe_resize(src_path, resize_mode, resize_width, resize_height, resize_modes)
        if resized_path != src_path and temp_files is not None:
            temp_files.append(resized_path)
           
        fname = os.path.basename(resized_path)
        name_root, original_ext = os.path.splitext(fname)
        ext = original_ext.lower()

        target_ext = original_ext if ext not in [".gif", ".bmp"] else ".png"
        dst_filename = name_root + target_ext
        dst_path = os.path.join(dst_dir, dst_filename)
        original_dst_path = os.path.join(dst_dir, name_root + original_ext)

        if os.path.isdir(dst_path):
            shutil.rmtree(dst_path, ignore_errors=True)
        elif os.path.exists(dst_path):
            os.remove(dst_path)

        legacy_dir = os.path.join(dst_dir, fname)
        if os.path.isdir(legacy_dir):
            shutil.rmtree(legacy_dir, ignore_errors=True)

        # 一時停止チェック
        if pause_callback and pause_callback():
            while pause_callback():
                time.sleep(0.1)  # 一時停止中は待機

        # コマンド組み立て
        if ext in [".jpg", ".jpeg"]:
            cmd = ["caesiumclt"]
            if not jpeg_keep_metadata:
                cmd.append("--exif-tool=delete")
            if jpeg_progressive:
                cmd.append("--progressive")
            cmd.extend(["--quality", str(jpeg_quality)])
        elif ext == ".webp":
            cmd = ["caesiumclt"]
            if not webp_keep_metadata:
                cmd.append("--exif-tool=delete")
            cmd.extend(["--quality", str(webp_quality)])
        elif ext == ".png":
            cmd = ["caesiumclt"]
            if not png_keep_metadata:
                cmd.append("--exif-tool=delete")
            cmd.extend(["--lossless", "--png-opt-level", str(png_compression_level)])
        elif ext == ".tiff":
            cmd = ["caesiumclt"]
            if not tiff_keep_metadata:
                cmd.append("--exif-tool=delete")
            cmd.append("--lossless")
        elif ext in [".gif", ".bmp"]:
            # GIFとBMPはPNGに変換して保存
            cmd = ["caesiumclt"]
            if not png_keep_metadata:
                cmd.append("--exif-tool=delete")
            cmd.extend(["--lossless", "--png-opt-level", str(png_compression_level), "--format", "png"])
        else:
            return (src_path, None, f"未対応の形式: {ext}")

        cmd.extend(["--output", dst_dir, resized_path])

        # 一時停止チェック
        if pause_callback and pause_callback():
            while pause_callback():
                time.sleep(0.1)  # 一時停止中は待機

        # Caesium CLTコマンド実行
        result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
       
        # エラーチェック
        if result.returncode != 0:
            # エラー時は元のファイルをそのままコピー（拡張子も元に戻す）
            if dst_path != original_dst_path and os.path.exists(dst_path):
                try:
                    os.remove(dst_path)
                except OSError:
                    pass
            dst_path = original_dst_path
            shutil.copy2(src_path, dst_path)
            return (src_path, dst_path, f"Caesium CLT エラー: {result.stderr}")
        else:
            if not os.path.isfile(dst_path):
                alt_candidates = [
                    os.path.join(dst_dir, fname),
                    os.path.join(dst_dir, os.path.basename(src_path))
                ]
                for candidate in alt_candidates:
                    if os.path.isfile(candidate):
                        dst_path = candidate
                        break
                else:
                    legacy_dir = os.path.join(dst_dir, fname)
                    if os.path.isdir(legacy_dir):
                        inner_files = [
                            os.path.join(legacy_dir, f)
                            for f in os.listdir(legacy_dir)
                            if os.path.isfile(os.path.join(legacy_dir, f))
                        ]
                        if inner_files:
                            target_file = inner_files[0]
                            final_path = os.path.join(dst_dir, os.path.basename(target_file))
                            if os.path.exists(final_path):
                                os.remove(final_path)
                            shutil.move(target_file, final_path)
                            shutil.rmtree(legacy_dir, ignore_errors=True)
                            dst_path = final_path

            # 正常終了
            # サイズチェック（スキップオプション有効時）
            if skip_if_larger and os.path.exists(dst_path):
                orig_size = os.path.getsize(src_path)
                new_size = os.path.getsize(dst_path)
                if new_size > orig_size:
                    try:
                        os.remove(dst_path)
                    except OSError:
                        pass
                    dst_path = original_dst_path
                    shutil.copy2(src_path, dst_path)
                    return (src_path, dst_path, "圧縮後のサイズが大きかったためスキップ")
            
            return (src_path, dst_path, None)  # 成功

    except Exception as e:
        # エラー時は元ファイルをコピー
        try:
            dst_path = original_dst_path
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            if not os.path.exists(dst_path):
                shutil.copy2(src_path, dst_path)
                return (src_path, dst_path, f"エラー発生、元ファイルコピー: {str(e)}")
        except Exception as copy_err:
            logger.exception(f"フォールバックコピーも失敗: {src_path} ({copy_err})")
        return (src_path, None, f"処理エラー: {str(e)}")

def maybe_resize(src_path, resize_mode, resize_width, resize_height, resize_modes):
    # リサイズ不要の場合
    if resize_mode == resize_modes[0]:
        return src_path

    img = None
    resized_img = None
    try:
        # 画像を開く
        img = Image.open(src_path)
        w, h = img.size
        new_w, new_h = w, h
        original_format = img.format

        # リサイズモードに応じた処理
        if resize_mode == resize_modes[1] and resize_width > 0:  # 幅優先
            if w > resize_width:  # 指定サイズより大きい場合のみリサイズ
                ratio = resize_width / w
                new_w = resize_width
                new_h = int(h * ratio)
        elif resize_mode == resize_modes[2] and resize_height > 0:  # 高さ優先
            if h > resize_height:  # 指定サイズより大きい場合のみリサイズ
                ratio = resize_height / h
                new_h = resize_height
                new_w = int(w * ratio)
        elif resize_mode == resize_modes[3] and resize_width > 0 and resize_height > 0:  # 指定サイズ
            new_w = resize_width
            new_h = resize_height

        # サイズが変わらない場合はそのまま返す
        if new_w == w and new_h == h:
            return src_path

        # リサイズ処理
        resized_img = img.resize((new_w, new_h), Image.LANCZOS)
        temp_path = src_path + "_resized" + os.path.splitext(src_path)[1]

        # 透過情報を保持（formatがNoneの場合は拡張子から推測される）
        if img.mode == 'RGBA' and original_format:
            resized_img.save(temp_path, format=original_format)
        else:
            resized_img.save(temp_path)

        return temp_path
    except Exception as e:
        logger.exception(f"Error in maybe_resize for {src_path}")
        return src_path
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass
        if resized_img is not None:
            try:
                resized_img.close()
            except Exception:
                pass

# 言語設定
def load_language():
    # 強制的に日本語を使用（警告を避ける）
    return {
        "title": "Caesium CLT 1.1",
        "input_files": "入力ファイル:",
        "browse": "参照",
        "output_folder": "出力先:",
        "selected_files": "選択されたファイル一覧（右クリックでメニュー表示）",
        "selected_count": "選択されたファイル: {}件",
        "compression": "圧縮",
        "resize": "サイズ変更",
        "output": "出力",
        "advanced": "高度な設定",  # 追加
        "execute": "実行",
        "quality": "品質(1-100):",
        "progressive": "プログレッシブ",
        "keep_metadata": "メタデータ保持",
        "compression_level": "圧縮レベル(0-9):",
        "resize_mode": "自動サイズ変更:",
        "width": "幅:",
        "height": "高さ:",
        "resize_note": "※幅優先・高さ優先の場合、もう片方は自動計算されます。",
        "output_settings": "出力設定",
        "skip_if_larger": "出力サイズが元より大きい場合はスキップ",
        "delete_original": "元ファイルを削除",
        "file_suffix": "ファイル名末尾に追加する文字列",
        "executing": "実行中...",
        "completed": "Completed",
        "error": "エラー",
        "no_input": "入力ファイルが選択されていません。",
        "no_output": "出力先フォルダが選択されていません。",
        "processing": "Processing: {} ({}/{})",
        "cancelled_progress": "Processing cancelled by user",
        "extract_complete": "解凍完了: {} → {}",
        "zip_complete": "ZIP作成完了: {}",
        "error_msg": "エラー: {}",
        "command": "実行コマンド: {}",
        "larger_file": "圧縮後が大きいため戻します: {}",
        "original_delete": "元ファイル削除: {}",
        "result": "処理結果",
        "processing_target": "[処理対象] {}",
        "start": "=== 実行開始 ===",
        "end": "=== 実行完了 ===",
        "new_zip": "→ 新ZIP作成: {}",
        "copy_date_fail": "日時コピー失敗: {}",
        "not_image_or_archive": "画像でもZIP/RARでもないためスキップ",
        "7z_missing": "7-Zip がインストールされていません。ZIPのみ処理されます。",
        "resize_modes": ["変更しない", "幅優先", "高さ優先", "指定サイズ"],
        "menu_delete": "削除",
        "menu_delete_all": "すべて削除",
        "menu_select_all": "すべて選択",
        "test_compression": "テスト圧縮",
        "settings": "設定",
        "about": "このアプリについて",
        "save_settings": "設定保存",
        "load_settings": "設定読込",
        "confirm_delete": "削除確認",
        "confirm_delete_msg": "選択したファイルをリストから削除しますか？",
        "about_text": "Caesium CLT GUI Tool\nVersion: 1.1\n\nA GUI application for image compression and archive processing.",
        "check_deps": "依存関係チェック",
        "multiple_folders": "複数のフォルダ構造を持つZIP/RARファイルのためスキップします: {}",
        # 追加設定
        "parallel_settings": "並列処理設定",
        "max_workers": "最大ワーカー数:",
        "batch_size": "バッチサイズ:",
        "memory_usage": "メモリ使用量: {}MB",
        "temp_dir": "一時ディレクトリ:",
        # 処理中画像表示用の項目
        "processing_image_preview": "処理中の画像",
        "no_image_processing": "処理中の画像はありません",
        # テスト出力関連の項目を追加
        "test_output_settings": "テスト出力設定",
        "use_test_output": "テスト出力先を使用",
        "test_output_folder": "テスト出力先:"
    }

LANG = load_language()

# エラーメッセージの日本語変換辞書
ERROR_TRANSLATIONS = {
    "No such file or directory": "ファイルまたはディレクトリが見つかりません",
    "Permission denied": "アクセス権限がありません",
    "File exists": "ファイルが既に存在します",
    "Not a directory": "ディレクトリではありません",
    "Is a directory": "ディレクトリです（ファイルが必要です）",
    "Invalid argument": "引数が無効です",
    "Too many open files": "開かれているファイルが多すぎます",
    "File too large": "ファイルサイズが大きすぎます",
    "Disk quota exceeded": "ディスク容量が不足しています",
    "Operation not permitted": "操作が許可されていません",
    "Broken pipe": "パイプが切断されました",
    "Connection refused": "接続が拒否されました",
    "Connection reset": "接続がリセットされました",
    "Connection timed out": "接続がタイムアウトしました",
    "No space left on device": "デバイスに空き容量がありません",
    "Read-only file system": "読み取り専用ファイルシステムです",
    "Resource temporarily unavailable": "リソースが一時的に利用できません",
    "Input/output error": "入出力エラーが発生しました",
    "Device or resource busy": "デバイスまたはリソースがビジー状態です",
    "Directory not empty": "ディレクトリが空ではありません",
    "Cannot allocate memory": "メモリを割り当てられません",
    "Bad file descriptor": "不正なファイル記述子です",
    "Resource unavailable": "リソースが利用できません",
    "Interrupted system call": "システムコールが中断されました",
    "File name too long": "ファイル名が長すぎます",
    "Out of memory": "メモリ不足です",
    "Out of range": "範囲外です",
    "Illegal operation": "不正な操作です",
    "Not implemented": "実装されていません",
    "Operation not supported": "サポートされていない操作です",
    "No such process": "プロセスが存在しません",
    "Inappropriate ioctl for device": "デバイスに対する不適切なI/O制御です"
}

class CaesiumCLTGUI(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(LANG["title"])
        # ウィンドウサイズを広く設定（拡大）
        self.geometry("1400x900")  # 横幅と高さを増加
        self.minsize(1200, 700)    # 最小サイズも拡大

        # アプリケーション設定（デフォルト値）
        self.config_file = os.path.join(os.path.expanduser("~"), ".caesium_gui_config.json")
    
        # メニューバー追加
        self.create_menu()

        # 入力ファイル（選択されたファイルのパス一覧）
        self.input_files = []
        # 出力先フォルダ：初期設定
        self.output_folder = tk.StringVar()
        
        # テスト出力先の設定（新規追加）
        self.test_output_folder = tk.StringVar(value="G:\\ダウンロード")
        self.use_test_output = tk.BooleanVar(value=False)

        # サイズ削減結果の集計（{入力パス: (元サイズ, 最終サイズ, スキップフラグ, スキップ理由)}）
        self.size_summary = {}

        # 処理中かどうかのフラグ
        self.processing = False
        self.temp_files = []  # 一時ファイルのリスト
        self.ui_queue = queue.Queue()
        self.after(50, self._process_ui_queue)
    
        # 一時ディレクトリの作成（アプリケーション終了時に削除）
        self.temp_dir = tempfile.mkdtemp()
        self._managed_temp_dirs = {self.temp_dir}
        self._current_temp_managed = True
        atexit.register(self.cleanup_temp_dir)

        # v2: 複数フォルダ構造は正常処理されるため、移動オプションは不要

        # プリセット管理用の変数を初期化（この行が重要）
        self.presets = {}
        self.preset_dir = os.path.join(os.path.expanduser("~"), ".caesium_presets")
        if not os.path.exists(self.preset_dir):
            os.makedirs(self.preset_dir, exist_ok=True)
        
        # 処理中画像表示用の変数
        self.current_processing_photo = None
        self.current_processing_path = None

        # 進捗追跡用の変数を追加
        self.processed_files = []  # 処理済みファイルのリスト
        self.current_archive = None  # 現在処理中の書籍ファイル（アーカイブ）

        # 進捗追跡用の変数を拡張
        self.start_time = None  # 処理開始時間
        self.processed_count = 0  # 処理済みファイル数
        self.total_count = 0  # 処理対象の実書籍数（フォルダ内を展開した総数）
        self.elapsed_time_label = None  # 経過時間表示用ラベル
        self.remaining_time_label = None  # 残り時間表示用ラベル
        self.processing_ratio_label = None  # 処理比率表示用ラベル

        # ログフォルダの作成
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_dir = os.path.join(script_dir, "log")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

        # ログファイルのパス（日付ベース）
        current_date = time.strftime("%Y_%m_%d")
        self.log_file_path = os.path.join(self.log_dir, f"{current_date}_progress.log")
        self.error_log_file_path = os.path.join(self.log_dir, f"{current_date}_errors.log")
        
        # v2: エラーログをCSV出力用に構造化して保存するリスト
        # 形式: [(タイムスタンプ, アーカイブ名, エラー種別, ファイル名, 詳細), ...]
        self.error_log_data = []

        # 定期的なログ保存タイマーを設定
        self.start_log_save_timer()

        # --- 圧縮タブの設定 ---
        # JPEG
        self.jpeg_quality = tk.IntVar(value=80)
        self.jpeg_progressive = tk.BooleanVar(value=False)
        self.jpeg_keep_metadata = tk.BooleanVar(value=True)
        # PNG
        self.png_compression_level = tk.IntVar(value=3)
        self.png_keep_metadata = tk.BooleanVar(value=True)
        # WebP
        self.webp_quality = tk.IntVar(value=80)
        self.webp_keep_metadata = tk.BooleanVar(value=True)
        # TIFF
        self.tiff_keep_metadata = tk.BooleanVar(value=True)

        # --- サイズ変更タブの設定 ---
        self.resize_mode = tk.StringVar(value=LANG["resize_modes"][0])
        self.resize_width = tk.IntVar(value=0)
        self.resize_height = tk.IntVar(value=0)

        # --- 出力タブの設定 ---
        self.skip_if_larger = tk.BooleanVar(value=True)
        self.skip_already_processed = tk.BooleanVar(value=True)  # 処理済みマーカー検出時にスキップ
        self.delete_original = tk.BooleanVar(value=False)
        self.file_suffix = tk.StringVar(value="")
        
        # --- 新機能：元ファイル削除モード ---
        self.delete_original_mode = tk.StringVar(value="trash")  # "trash" または "permanent"
        
        # --- 新機能：処理後自動置き換えオプション ---
        self.auto_replace_enabled = tk.BooleanVar(value=True)  # ON/OFFフラグ
        self.original_backup_folder = tk.StringVar(value="F:/漫画")   # 元ファイルの移動先フォルダ

        # --- 入力時除外パターン（フォルダ/ファイル名にこれらの文字列を含むものはリストに追加しない） ---
        self.excluded_name_patterns = ["話巻", "(Toomics)", "(レジンコミックス)", "(TOPTOON)", "(コミックシーモア)"]
        
        # --- 高度な設定タブ（追加） ---
        self.max_workers = tk.IntVar(value=20)  # Ryzen 9 5900X向け最適値
        self.batch_size = tk.IntVar(value=50)   # 64GBメモリ向け最適値
        self.temp_dir_var = tk.StringVar(value=self.temp_dir)
        
        # --- 履歴管理の追加 ---
        self.history_file = os.path.join(os.path.expanduser("~"), ".caesium_history.json")
        self.history = self.load_history()

        # --- プレビュー表示の初期設定（起動時オフ） ---
        self.preview_enabled = tk.BooleanVar(value=False)

        # 設定を読み込む
        self.load_config()
        
        # UIコンポーネント作成
        self.create_widgets()

        # ドラッグ＆ドロップ対応のためウィンドウ全体を登録
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop_files)
        self.dnd_bind('<<DragEnter>>', self.on_drag_enter)
        self.dnd_bind('<<DragLeave>>', self.on_drag_leave)
        
        # 7zコマンドの確認
        self.has_7z = self.check_7z()
        if not self.has_7z:
            self.log(LANG["7z_missing"])
            
        # Caesium CLTコマンドの確認
        if not self.check_caesium_clt():
            self.log_error("Caesium CLT がインストールされていません。")
            messagebox.showerror("Error", "Caesium CLT がインストールされていません。\nhttps://saerasoft.com/caesium/ からダウンロードしてください。")
        
        # 定期的にメモリ使用量を更新
        self.update_memory_usage()

        # 処理の一時停止フラグ
        self.pause_processing = False
        
        # 処理中止フラグ
        self.cancel_processing = False
        
        # ウィンドウを閉じる際の処理を設定
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """アプリケーションを閉じる前の確認"""
        if self.processing:
            if messagebox.askokcancel("警告", "処理が実行中です。中止して終了しますか？"):
                # 処理を中止
                self.cancel_processing = True
                self._silent_save_config()
                # 少し待ってから終了
                self.after(500, self.destroy)
        else:
            self._silent_save_config()
            self.destroy()

    def _silent_save_config(self):
        """終了時などに設定をダイアログなしで保存する。"""
        try:
            config = {
                "output_folder": self.output_folder.get(),
                "jpeg_quality": self.jpeg_quality.get(),
                "jpeg_progressive": self.jpeg_progressive.get(),
                "jpeg_keep_metadata": self.jpeg_keep_metadata.get(),
                "png_compression_level": self.png_compression_level.get(),
                "png_keep_metadata": self.png_keep_metadata.get(),
                "webp_quality": self.webp_quality.get(),
                "webp_keep_metadata": self.webp_keep_metadata.get(),
                "tiff_keep_metadata": self.tiff_keep_metadata.get(),
                "resize_mode": self.resize_mode.get(),
                "resize_width": self.resize_width.get(),
                "resize_height": self.resize_height.get(),
                "skip_if_larger": self.skip_if_larger.get(),
                "skip_already_processed": self.skip_already_processed.get(),
                "delete_original": self.delete_original.get(),
                "delete_original_mode": self.delete_original_mode.get(),
                "file_suffix": self.file_suffix.get(),
                "max_workers": self.max_workers.get(),
                "batch_size": self.batch_size.get(),
                "temp_dir": self.temp_dir_var.get(),
                "preview_enabled": self.preview_enabled.get(),
                "use_test_output": self.use_test_output.get(),
                "test_output_folder": self.test_output_folder.get(),
                "auto_replace_enabled": self.auto_replace_enabled.get(),
                "original_backup_folder": self.original_backup_folder.get(),
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            try:
                self.log_error(f"自動設定保存エラー: {e}")
            except Exception:
                pass

    def start_log_save_timer(self):
        """定期的にログを保存するタイマーを開始"""
        self.save_logs_to_file()  # 実行
        # 60秒ごとにログを保存
        self.after(60000, self.start_log_save_timer)

    def save_logs_to_file(self):
        """ログと進捗情報をファイルに保存"""
        try:
            # 現在の日付を取得
            current_date = time.strftime("%Y_%m_%d")
            self.log_file_path = os.path.join(self.log_dir, f"{current_date}_progress.log")
            self.error_log_file_path = os.path.join(self.log_dir, f"{current_date}_errors.log")
            
            # 進捗ログを保存
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                f.write(f"=== Caesium GUI 進捗ログ - {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                f.write(f"処理済みファイル: {len(self.processed_files)}/{len(self.input_files) if hasattr(self, 'input_files') else 0}\n\n")
                f.write("--- 処理済みファイル一覧 ---\n")
                for i, file_path in enumerate(self.processed_files):
                    f.write(f"{i+1}. {file_path}\n")
                
                # 現在処理中のファイルがあれば記録
                if self.current_archive:
                    f.write(f"\n現在処理中: {self.current_archive}\n")
            
            # エラーログを保存（エラーログテキストがある場合のみ）
            if hasattr(self, 'error_log_text') and self.error_log_text:
                with open(self.error_log_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"=== Caesium GUI エラーログ - {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                    try:
                        # エラーログテキストからテキストを取得
                        error_log_content = self.error_log_text.get(1.0, tk.END)
                        f.write(error_log_content)
                    except Exception as e:
                        f.write(f"エラーログの取得に失敗しました: {e}\n")
                        # 代わりに記録済みエラーを書き込む
                        if hasattr(self, '_recorded_errors') and self._recorded_errors:
                            f.write("\n記録済みエラー:\n")
                            for err in self._recorded_errors:
                                f.write(f"{err}\n")
        except Exception as e:
            print(f"ログ保存エラー: {e}")  # コンソールに出力

    def create_menu(self):
        """メニューバーを作成"""
        menubar = Menu(self)
        
        # ファイルメニュー
        self.file_menu = Menu(menubar, tearoff=0)
        self.file_menu.add_command(label=LANG["save_settings"], command=self.save_config)
        self.file_menu.add_command(label=LANG["load_settings"], command=self.load_config)
        self.file_menu.add_separator()
        
        # プリセットサブメニューの追加
        preset_menu = Menu(self.file_menu, tearoff=0)
        preset_menu.add_command(label="現在の設定をプリセットとして保存", command=self.save_preset)
        preset_menu.add_command(label="プリセットを読み込む", command=self.load_preset)
        preset_menu.add_command(label="プリセット管理", command=self.show_preset_manager)  # 追加
        preset_menu.add_separator()
        
        # preset_dirが確実に初期化されていることを確認
        if hasattr(self, 'preset_dir'):
            self.update_preset_menu(preset_menu)
        else:
            # 初期化されていない場合は簡易項目を追加
            preset_menu.add_command(label="プリセットなし", state=tk.DISABLED)
        
        self.file_menu.add_cascade(label="プリセット", menu=preset_menu)
        self.file_menu.add_separator()
    
        self.file_menu.add_command(label=LANG["check_deps"], command=self.check_dependencies)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="終了", command=self.quit)
        menubar.add_cascade(label="ファイル", menu=self.file_menu)
    
        # ツールメニュー
        tools_menu = Menu(menubar, tearoff=0)
        tools_menu.add_command(label=LANG["test_compression"], command=self.test_compression)
        tools_menu.add_command(label="処理履歴を表示", command=self.show_history)  # 追加
    
        menubar.add_cascade(label="ツール", menu=tools_menu)
    
        # ヘルプメニュー
        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label=LANG["about"], command=self.show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
    
        self.config(menu=menubar)

    def update_preset_menu(self, menu):
        """プリセットメニューを更新"""
        # 既存の項目をすべて削除（区切り以降）
        menu_size = menu.index(tk.END)
        if menu_size is not None and menu_size > 2:
            for i in range(3, menu_size + 1):
                menu.delete(3)
    
        # プリセットファイルを検索
        preset_files = [f for f in os.listdir(self.preset_dir) if f.endswith('.json')]
    
        if preset_files:
            for preset_file in preset_files:
                preset_name = os.path.splitext(preset_file)[0]
                menu.add_command(label=preset_name, command=lambda name=preset_name: self.apply_preset(name))
        else:
            # プリセットがなければ無効な項目を表示
            menu.add_command(label="保存されたプリセットはありません", state=tk.DISABLED)

    def save_preset(self):
        """現在の設定をプリセットとして保存"""
        preset_name = simpledialog.askstring("プリセット保存", "プリセット名を入力してください:")
        if not preset_name:
            return
        
        # ファイル名に使用できない文字を置換
        preset_name = preset_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
        
        preset = {
            "jpeg_quality": self.jpeg_quality.get(),
            "jpeg_progressive": self.jpeg_progressive.get(),
            "jpeg_keep_metadata": self.jpeg_keep_metadata.get(),
            "png_compression_level": self.png_compression_level.get(),
            "png_keep_metadata": self.png_keep_metadata.get(),
            "webp_quality": self.webp_quality.get(),
            "webp_keep_metadata": self.webp_keep_metadata.get(),
            "tiff_keep_metadata": self.tiff_keep_metadata.get(),
            "resize_mode": self.resize_mode.get(),
            "resize_width": self.resize_width.get(),
            "resize_height": self.resize_height.get(),
            "skip_if_larger": self.skip_if_larger.get(),
            "delete_original": self.delete_original.get(),
            "delete_original_mode": self.delete_original_mode.get(),  # 追加
            "file_suffix": self.file_suffix.get(),
            "max_workers": self.max_workers.get(),
            "batch_size": self.batch_size.get(),
            "created_date": time.strftime("%Y-%m-%d %H:%M:%S"),  # 作成日時を追加
            "use_test_output": self.use_test_output.get(),  # テスト出力設定を追加
            "test_output_folder": self.test_output_folder.get(),  # テスト出力先を追加
            "auto_replace_enabled": self.auto_replace_enabled.get(),  # 自動置き換え
            "original_backup_folder": self.original_backup_folder.get()  # 元ファイル移動先
        }
        
        # プリセットディレクトリの確認
        if not os.path.exists(self.preset_dir):
            os.makedirs(self.preset_dir, exist_ok=True)
        
        # プリセットをファイルに保存
        preset_path = os.path.join(self.preset_dir, f"{preset_name}.json")
        try:
            with open(preset_path, 'w', encoding='utf-8') as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
            
            # メニューを更新
            preset_menu = self.file_menu.nametowidget(self.file_menu.entrycget("プリセット", "menu"))
            self.update_preset_menu(preset_menu)
            
            messagebox.showinfo("保存完了", f"プリセット '{preset_name}' を保存しました")
        except Exception as e:
            messagebox.showerror("エラー", f"プリセット保存中にエラーが発生しました: {e}")
            logger.exception(f"プリセット保存エラー: {e}")

    def load_preset(self):
        """プリセットの読み込みダイアログを表示"""
        preset_files = [os.path.splitext(f)[0] for f in os.listdir(self.preset_dir) if f.endswith('.json')]
        if not preset_files:
            messagebox.showinfo("プリセット", "保存されたプリセットはありません")
            return
    
        # プリセット選択ダイアログ
        preset_name = simpledialog.askstring(
            "プリセット読み込み", 
            "読み込むプリセット名を入力してください:",
            initialvalue=preset_files[0] if preset_files else ""
        )
    
        if preset_name:
            self.apply_preset(preset_name)

    def apply_preset(self, preset_name):
        """指定された名前のプリセットを適用"""
        preset_path = os.path.join(self.preset_dir, f"{preset_name}.json")
        if not os.path.exists(preset_path):
            messagebox.showerror("エラー", f"プリセット '{preset_name}' が見つかりません")
            return
        
        try:
            with open(preset_path, 'r', encoding='utf-8') as f:
                preset = json.load(f)
            
            # プリセットの設定を適用
            if "jpeg_quality" in preset: self.jpeg_quality.set(preset["jpeg_quality"])
            if "jpeg_progressive" in preset: self.jpeg_progressive.set(preset["jpeg_progressive"])
            if "jpeg_keep_metadata" in preset: self.jpeg_keep_metadata.set(preset["jpeg_keep_metadata"])
            if "png_compression_level" in preset: self.png_compression_level.set(preset["png_compression_level"])
            if "png_keep_metadata" in preset: self.png_keep_metadata.set(preset["png_keep_metadata"])
            if "webp_quality" in preset: self.webp_quality.set(preset["webp_quality"])
            if "webp_keep_metadata" in preset: self.webp_keep_metadata.set(preset["webp_keep_metadata"])
            if "tiff_keep_metadata" in preset: self.tiff_keep_metadata.set(preset["tiff_keep_metadata"])
            if "resize_mode" in preset: self.resize_mode.set(preset["resize_mode"])
            if "resize_width" in preset: self.resize_width.set(preset["resize_width"])
            if "resize_height" in preset: self.resize_height.set(preset["resize_height"])
            if "skip_if_larger" in preset: self.skip_if_larger.set(preset["skip_if_larger"])
            if "delete_original" in preset: self.delete_original.set(preset["delete_original"])
            if "file_suffix" in preset: self.file_suffix.set(preset["file_suffix"])
            if "max_workers" in preset: self.max_workers.set(preset["max_workers"])
            if "batch_size" in preset: self.batch_size.set(preset["batch_size"])
            if "delete_original_mode" in preset: self.delete_original_mode.set(preset["delete_original_mode"])
            # テスト出力設定も読み込み
            if "use_test_output" in preset: self.use_test_output.set(preset["use_test_output"])
            if "test_output_folder" in preset: self.test_output_folder.set(preset["test_output_folder"])
            if "auto_replace_enabled" in preset: self.auto_replace_enabled.set(preset["auto_replace_enabled"])
            if "original_backup_folder" in preset: self.original_backup_folder.set(preset["original_backup_folder"])
            
            self.log(f"プリセット '{preset_name}' を適用しました")
            messagebox.showinfo("プリセット適用", f"プリセット '{preset_name}' を適用しました")
        except Exception as e:
            self.log_error(f"プリセット適用中にエラーが発生しました: {e}")
            messagebox.showerror("エラー", f"プリセット適用中にエラーが発生しました: {e}")
            logger.exception(f"プリセット適用エラー: {e}")

    def create_compression_tab(self, parent):
        # JPEG設定
        frame_jpeg = ttk.LabelFrame(parent, text="JPEG")
        frame_jpeg.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_jpeg, text=LANG["quality"]).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        tk.Scale(frame_jpeg, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.jpeg_quality).grid(row=0, column=1, sticky="we", padx=5, pady=5)
        tk.Checkbutton(frame_jpeg, text=LANG["progressive"], variable=self.jpeg_progressive).grid(row=1, column=0, columnspan=2, sticky="w", padx=5)
        tk.Checkbutton(frame_jpeg, text=LANG["keep_metadata"], variable=self.jpeg_keep_metadata).grid(row=2, column=0, columnspan=2, sticky="w", padx=5)

        # PNG設定
        frame_png = ttk.LabelFrame(parent, text="PNG")
        frame_png.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_png, text=LANG["compression_level"]).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        tk.Scale(frame_png, from_=0, to=9, orient=tk.HORIZONTAL, variable=self.png_compression_level).grid(row=0, column=1, sticky="we", padx=5, pady=5)
        tk.Checkbutton(frame_png, text=LANG["keep_metadata"], variable=self.png_keep_metadata).grid(row=1, column=0, columnspan=2, sticky="w", padx=5)

        # WebP設定
        frame_webp = ttk.LabelFrame(parent, text="WebP")
        frame_webp.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_webp, text=LANG["quality"]).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        tk.Scale(frame_webp, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.webp_quality).grid(row=0, column=1, sticky="we", padx=5, pady=5)
        tk.Checkbutton(frame_webp, text=LANG["keep_metadata"], variable=self.webp_keep_metadata).grid(row=1, column=0, columnspan=2, sticky="w", padx=5)

        # TIFF設定
        frame_tiff = ttk.LabelFrame(parent, text="TIFF")
        frame_tiff.pack(fill=tk.X, padx=5, pady=5)
        tk.Checkbutton(frame_tiff, text=LANG["keep_metadata"], variable=self.tiff_keep_metadata).pack(anchor="w", padx=5, pady=5)

    def create_resize_tab(self, parent):
        tk.Label(parent, text=LANG["resize_mode"]).pack(anchor="w", padx=10, pady=5)
        ttk.Combobox(parent, textvariable=self.resize_mode, values=LANG["resize_modes"], state="readonly").pack(anchor="w", padx=10)
        size_frame = tk.Frame(parent)
        size_frame.pack(anchor="w", padx=10, pady=10)
        tk.Label(size_frame, text=LANG["width"]).grid(row=0, column=0, padx=5, pady=5, sticky="e")
        tk.Entry(size_frame, textvariable=self.resize_width, width=10).grid(row=0, column=1, padx=5, pady=5)
        tk.Label(size_frame, text=LANG["height"]).grid(row=1, column=0, padx=5, pady=5, sticky="e")
        tk.Entry(size_frame, textvariable=self.resize_height, width=10).grid(row=1, column=1, padx=5, pady=5)
        tk.Label(parent, text=LANG["resize_note"]).pack(anchor="w", padx=10)

    def create_widgets(self):
        # メインフレームを左右に分割
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左側: 主要機能エリア
        left_frame = tk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 右側: 処理中画像表示エリア
        right_frame = tk.Frame(main_frame, width=300, bg="#f0f0f0", bd=1, relief=tk.SUNKEN)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)
        right_frame.pack_propagate(False)  # サイズ固定

        # プレビュー設定用フレーム
        preview_control_frame = tk.Frame(right_frame, bg="#f0f0f0")
        preview_control_frame.pack(pady=(5, 0), fill=tk.X)
        
        # プレビュー有効/無効の切り替え
        tk.Checkbutton(preview_control_frame, text="プレビュー表示", 
                      variable=self.preview_enabled, bg="#f0f0f0",
                      command=self.toggle_preview).pack(side=tk.LEFT, padx=5)

        # リフレッシュボタン
        tk.Button(preview_control_frame, text="更新", command=self.refresh_preview,
                 width=6).pack(side=tk.RIGHT, padx=5)

        # 処理中画像のラベル
        tk.Label(right_frame, text=LANG["processing_image_preview"], 
                 bg="#f0f0f0", font=("", 12, "bold")).pack(pady=(5, 10))
        
        # 画像表示用キャンバス
        self.image_canvas = tk.Canvas(right_frame, bg="#f0f0f0", width=280, height=280, bd=0, highlightthickness=0)
        self.image_canvas.pack(padx=10, pady=5)
        
        # 画像情報表示用ラベル
        self.image_info_label = tk.Label(right_frame, text=LANG["no_image_processing"], 
                                         bg="#f0f0f0", wraplength=280, justify=tk.LEFT)
        self.image_info_label.pack(padx=10, pady=5, fill=tk.X)

        # --- 左側フレーム内のコンポーネント ---
        # 上部：入力ファイルと出力先の設定
        top_frame = tk.Frame(left_frame)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        tk.Label(top_frame, text=LANG["input_files"]).pack(side=tk.LEFT)
        tk.Button(top_frame, text=LANG["browse"], command=self.select_input_files).pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="フォルダ選択", command=self.select_input_folder).pack(side=tk.LEFT, padx=2)
        tk.Label(top_frame, text=f"  {LANG['output_folder']}").pack(side=tk.LEFT, padx=(20, 0))
        tk.Entry(top_frame, textvariable=self.output_folder, width=30).pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text=LANG["browse"], command=self.select_output_folder).pack(side=tk.LEFT, padx=5)

        # 出力モード: 通常出力 / 処理後自動置き換え（選ばれた方を強調、他方をディム）
        mode_frame = tk.Frame(top_frame)
        mode_frame.pack(side=tk.LEFT, padx=(15, 0))
        self._rb_normal = tk.Radiobutton(mode_frame, text="通常出力",
                                         variable=self.auto_replace_enabled, value=False)
        self._rb_normal.pack(side=tk.LEFT)
        self._rb_auto = tk.Radiobutton(mode_frame, text="処理後自動置き換え",
                                       variable=self.auto_replace_enabled, value=True)
        self._rb_auto.pack(side=tk.LEFT, padx=(5, 0))

        # 元ファイル移動先（自動置き換えの右に配置）
        tk.Label(top_frame, text="  元ファイル移動先:").pack(side=tk.LEFT, padx=(15, 0))
        self._backup_entry = tk.Entry(top_frame, textvariable=self.original_backup_folder, width=20)
        self._backup_entry.pack(side=tk.LEFT, padx=5)
        self._backup_btn = tk.Button(top_frame, text=LANG["browse"], command=self.select_backup_folder)
        self._backup_btn.pack(side=tk.LEFT, padx=5)

        def _update_mode_visual(*_args):
            try:
                if self.auto_replace_enabled.get():
                    self._rb_auto.config(fg="black", font=("", 9, "bold"))
                    self._rb_normal.config(fg="gray60", font=("", 9, ""))
                    self._backup_entry.config(state="normal", fg="black")
                    self._backup_btn.config(state="normal")
                else:
                    self._rb_auto.config(fg="gray60", font=("", 9, ""))
                    self._rb_normal.config(fg="black", font=("", 9, "bold"))
                    self._backup_entry.config(state="disabled")
                    self._backup_btn.config(state="disabled")
            except Exception:
                pass

        self.auto_replace_enabled.trace_add("write", _update_mode_visual)
        _update_mode_visual()

        # ファイル一覧表示エリア（Listbox）とスクロールバー
        list_frame = tk.Frame(left_frame)
        list_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        # ファイル情報ヘッダーフレーム（ファイル数と処理中ファイル表示用）
        file_info_frame = tk.Frame(list_frame)
        file_info_frame.pack(fill=tk.X, anchor="w")
        tk.Label(file_info_frame, text=LANG["selected_files"]).pack(side=tk.LEFT)
        self.label_selected = tk.Label(file_info_frame, text=LANG["selected_count"].format(0))
        self.label_selected.pack(side=tk.LEFT, padx=10)
        
        # 現在処理中のファイル表示ラベル（新規追加）
        self.current_file_label = tk.Label(file_info_frame, text="", font=("", 9, ""))
        self.current_file_label.pack(side=tk.LEFT, padx=10)
        
        list_subframe = tk.Frame(list_frame)
        list_subframe.pack(fill=tk.X, padx=5, pady=5)
        
        # スクロールバー追加
        scrollbar = tk.Scrollbar(list_subframe)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ファイル一覧をTreeviewで表示（名前/状況/圧縮率の3列）
        self.file_tree = ttk.Treeview(
            list_subframe, columns=("status", "ratio"), height=8, selectmode="extended"
        )
        self.file_tree.heading("#0", text="名前")
        self.file_tree.heading("status", text="状況")
        self.file_tree.heading("ratio", text="圧縮率")
        self.file_tree.column("#0", width=420, anchor="w")
        self.file_tree.column("status", width=80, anchor="center")
        self.file_tree.column("ratio", width=80, anchor="e")
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.file_tree.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.file_tree.yview)

        self.file_tree.bind("<Delete>", self.on_delete_selection)
        self.file_tree.bind("<Button-3>", self.show_listbox_menu)

        # ステータス色分け
        self.file_tree.tag_configure("processing", foreground="#1565C0")  # 青
        self.file_tree.tag_configure("done", foreground="#2E7D32")  # 緑
        self.file_tree.tag_configure("skipped", foreground="#EF6C00")  # 橙
        self.file_tree.tag_configure("error", foreground="#C62828")  # 赤

        # path → item id の双方向マップ
        self._tree_item_by_path = {}
        self._tree_path_by_item = {}

        # プログレスバー
        self.progress_frame = tk.Frame(left_frame)
        self.progress_frame.pack(side=tk.TOP, fill=tk.X, padx=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)
        
        # システムリソース情報表示用フレーム
        resource_frame = tk.Frame(self.progress_frame)
        resource_frame.pack(anchor="e", padx=5, fill=tk.X)

        # 進捗情報の詳細表示フレーム（新規追加）
        progress_info_frame = tk.Frame(self.progress_frame)
        progress_info_frame.pack(fill=tk.X, padx=5, pady=2)
        
        # 処理比率表示（新規追加）
        self.processing_ratio_label = tk.Label(progress_info_frame, text="処理済み: 0/0", anchor="w")
        self.processing_ratio_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # 経過時間表示（新規追加）
        self.elapsed_time_label = tk.Label(progress_info_frame, text="経過時間: 00:00:00", anchor="w")
        self.elapsed_time_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # 残り時間表示（新規追加）
        self.remaining_time_label = tk.Label(progress_info_frame, text="残り時間: --:--:--", anchor="w")
        self.remaining_time_label.pack(side=tk.LEFT, padx=(0, 10))

        # 既存のラベル
        self.progress_label = tk.Label(self.progress_frame, text="")
        self.progress_label.pack(anchor="w", padx=5)

        # CPU使用率表示
        self.cpu_label = tk.Label(resource_frame, text="CPU使用率: 0%", fg="#009900")
        self.cpu_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # メモリ使用量表示
        self.memory_label = tk.Label(resource_frame, text="メモリ使用量: 0MB", fg="#000099")
        self.memory_label.pack(side=tk.LEFT)

        # Notebook タブ（圧縮・サイズ変更・出力・高度な設定）
        notebook = ttk.Notebook(left_frame)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tab_compression = ttk.Frame(notebook)
        self.tab_resize = ttk.Frame(notebook)
        self.tab_output = ttk.Frame(notebook)
        self.tab_advanced = ttk.Frame(notebook)
        
        notebook.add(self.tab_compression, text=LANG["compression"])
        notebook.add(self.tab_resize, text=LANG["resize"])
        notebook.add(self.tab_output, text=LANG["output"])
        notebook.add(self.tab_advanced, text=LANG["advanced"])
        
        self.create_compression_tab(self.tab_compression)
        self.create_resize_tab(self.tab_resize)
        self.create_output_tab(self.tab_output)
        self.create_advanced_tab(self.tab_advanced)

        # ボタン用フレーム（右側に配置）
        button_frame = tk.Frame(resource_frame)
        button_frame.pack(side=tk.RIGHT, padx=5)
        
        # 中止ボタン（3の位置）
        self.cancel_button = tk.Button(
            button_frame, 
            text="中止", 
            command=self.confirm_cancel, 
            bg="#FF6666", 
            width=8,
            height=2,
            font=("", 10, "bold")
        )
        self.cancel_button.pack(side=tk.LEFT, padx=2)
        
        # 一時停止ボタン（2の位置）
        self.pause_button = tk.Button(
            button_frame, 
            text="一時停止", 
            command=self.toggle_pause_action, 
            bg="#FFCC66",
            width=8,
            height=2,
            font=("", 10, "bold")
        )
        self.pause_button.pack(side=tk.LEFT, padx=2)
        
        # 実行ボタン（1の位置、大きいサイズ）
        self.execute_button = tk.Button(
            button_frame, 
            text=LANG["execute"], 
            command=self.start_execute, 
            bg="#66CC66",
            width=8,
            height=2,
            font=("", 10, "bold")
        )
        self.execute_button.pack(side=tk.LEFT, padx=2)

        # ログ表示エリア（ログとエラーログを分ける）
        log_frames = tk.Frame(left_frame)
        log_frames.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 通常ログ
        log_frame = tk.Frame(log_frames)
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
        
        log_label = tk.Label(log_frame, text="処理ログ")
        log_label.pack(anchor="w")
        
        log_scrollbar = tk.Scrollbar(log_frame)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # スクロールバーとテキストエリアを連動
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        log_scrollbar.config(command=self.log_text.yview)
        
        # エラーログ
        error_frame = tk.Frame(log_frames)
        error_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2, 0))
        
        # エラーログヘッダー（ラベルとCSV出力ボタン）
        error_header = tk.Frame(error_frame)
        error_header.pack(fill=tk.X)
        error_label = tk.Label(error_header, text="エラー・スキップログ", fg="red")
        error_label.pack(side=tk.LEFT, anchor="w")
        
        # v2: CSV出力ボタン
        self.csv_export_button = tk.Button(
            error_header, 
            text="CSV出力", 
            command=self.export_error_log_csv,
            width=8,
            font=("", 8)
        )
        self.csv_export_button.pack(side=tk.RIGHT, padx=2)
        
        error_scrollbar = tk.Scrollbar(error_frame)
        error_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.error_log_text = tk.Text(error_frame, height=10, wrap=tk.WORD, bg="#fff0f0")
        self.error_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
     
        # タグ設定
        self.error_log_text.tag_configure("error", foreground="red")
        self.error_log_text.tag_configure("skip", foreground="blue")
        self.error_log_text.tag_configure("timestamp", foreground="#606060")
        
        # スクロールバーとテキストエリアを連動
        self.error_log_text.config(yscrollcommand=error_scrollbar.set)
        error_scrollbar.config(command=self.error_log_text.yview)

        self.pause_button.config(state=tk.DISABLED) 
        
        # 起動時にプレビューがオフの場合は表示を更新
        self.toggle_preview()
        
        # UIコンポーネント作成後にログ保存タイマーを開始
        self.after(1000, self.start_log_save_timer)  # 1秒後にタイマー開始

    def update_file_count(self):
        """ファイル数表示を更新"""
        self.label_selected.config(text=LANG["selected_count"].format(len(self.input_files)))

    def on_drag_enter(self, event):
        """ドラッグ開始時の処理（簡略化）"""
        pass

    def on_drag_leave(self, event):
        """ドラッグ終了時の処理（簡略化）"""
        pass

    # ---- Treeview 操作ヘルパー ----
    def _tree_add_top(self, path, is_folder):
        """トップレベル行を追加。フォルダの場合は内部の書籍を子要素として展開する。"""
        try:
            base = os.path.basename(path.rstrip("/\\")) or path
            display = f"[フォルダ] {base}" if is_folder else base
            iid = self.file_tree.insert("", "end", text=display, values=("待機", ""))
            self._tree_item_by_path[path] = iid
            self._tree_path_by_item[iid] = path

            if is_folder:
                ARC_EXTS = {".zip", ".cbz", ".rar"}
                for root, dirs, files in os.walk(path):
                    # 除外パターンに一致するサブフォルダは降りない
                    dirs[:] = [d for d in dirs if not any(pat and pat in d for pat in self.excluded_name_patterns)]
                    for f in files:
                        if os.path.splitext(f)[1].lower() in ARC_EXTS:
                            full = os.path.join(root, f)
                            if self._is_excluded_path(full, base=path):
                                continue
                            rel = os.path.relpath(full, path)
                            child_iid = self.file_tree.insert(iid, "end", text=rel, values=("待機", ""))
                            self._tree_item_by_path[full] = child_iid
                            self._tree_path_by_item[child_iid] = full
        except Exception as e:
            logger.exception(f"_tree_add_top error: {e}")

    def update_tree_status(self, path, status, ratio_text=None):
        """指定パスの行の状況・圧縮率を更新する（UIスレッドから呼ぶこと）。"""
        iid = self._tree_item_by_path.get(path)
        if not iid:
            return
        try:
            if not self.file_tree.exists(iid):
                return
            current_values = self.file_tree.item(iid, "values")
            new_status = status if status is not None else (current_values[0] if current_values else "")
            new_ratio = ratio_text if ratio_text is not None else (current_values[1] if len(current_values) > 1 else "")
            tag_map = {"処理中": "processing", "完了": "done", "スキップ": "skipped", "エラー": "error"}
            tag = tag_map.get(new_status, "")
            self.file_tree.item(iid, values=(new_status, new_ratio), tags=(tag,) if tag else ())
            # 表示中の行までスクロール
            self.file_tree.see(iid)
            # 親フォルダがあれば集約状況を更新
            parent_iid = self.file_tree.parent(iid)
            if parent_iid:
                parent_path = self._tree_path_by_item.get(parent_iid)
                if parent_path:
                    self._aggregate_folder_status(parent_path)
        except Exception as e:
            logger.exception(f"update_tree_status error: {e}")

    def _aggregate_folder_status(self, folder_path):
        """フォルダ配下の子要素状況を集約してフォルダ行のステータスを更新する。"""
        iid = self._tree_item_by_path.get(folder_path)
        if not iid or not self.file_tree.exists(iid):
            return
        children = self.file_tree.get_children(iid)
        if not children:
            return
        statuses = []
        for c in children:
            v = self.file_tree.item(c, "values")
            statuses.append(v[0] if v else "")

        terminal = {"完了", "スキップ", "エラー"}
        if all(s in terminal for s in statuses):
            # 全件確定。圧縮率はsize_summaryの集計を使用
            ratio_text = ""
            if folder_path in self.size_summary:
                data = self.size_summary[folder_path]
                if len(data) >= 3 and not data[2] and data[0] > 0:
                    ratio = (1 - data[1] / data[0]) * 100
                    ratio_text = f"{ratio:.1f}%"
            done_count = sum(1 for s in statuses if s == "完了")
            label = "完了" if done_count == len(statuses) else f"完了({done_count}/{len(statuses)})"
            tag = "done" if done_count == len(statuses) else "skipped"
            self.file_tree.item(iid, values=(label, ratio_text), tags=(tag,))
        elif any(s == "処理中" for s in statuses):
            self.file_tree.item(iid, values=("処理中", ""), tags=("processing",))

    def _tree_clear_all(self):
        """ツリービューを空にする。"""
        try:
            for iid in self.file_tree.get_children():
                self.file_tree.delete(iid)
        except Exception:
            pass
        self._tree_item_by_path.clear()
        self._tree_path_by_item.clear()

    def _selected_top_paths(self):
        """選択行のうち、トップレベル(=input_files)に対応するパスのみ返す。"""
        result = []
        for iid in self.file_tree.selection():
            if self.file_tree.parent(iid):
                continue  # 子要素は無視
            p = self._tree_path_by_item.get(iid)
            if p:
                result.append((iid, p))
        return result

    # ファイル削除関連のメソッド
    def on_delete_selection(self, event):
        """Deleteキーでツリービュー上の選択項目を削除"""
        if self.processing:
            return

        targets = self._selected_top_paths()
        if not targets:
            return

        if messagebox.askyesno(LANG["confirm_delete"], LANG["confirm_delete_msg"]):
            for iid, path in targets:
                # 子要素のマップも削除
                for child in self.file_tree.get_children(iid):
                    cp = self._tree_path_by_item.pop(child, None)
                    if cp:
                        self._tree_item_by_path.pop(cp, None)
                self.file_tree.delete(iid)
                self._tree_item_by_path.pop(path, None)
                self._tree_path_by_item.pop(iid, None)
                if path in self.input_files:
                    self.input_files.remove(path)

            self.update_file_count()

    # 以下の新しいメソッドを追加
    def toggle_preview(self):
        """プレビュー表示のオン/オフを切り替え"""
        if not self.preview_enabled.get():
            # プレビューを無効化
            self.image_canvas.delete("all")
            self.image_info_label.config(text="プレビュー表示は無効になっています")
            self.current_processing_path = None
            self.current_processing_photo = None
        else:
            # プレビューを有効化（現在処理中のものがあれば表示）
            self.image_info_label.config(text=LANG["no_image_processing"])
            # 現在処理中のファイルがあれば表示を更新
            if hasattr(self, 'current_archive') and self.current_archive:
                self.refresh_preview()

    def refresh_preview(self):
        """現在の処理状態に基づいてプレビュー表示を更新"""
        if not self.preview_enabled.get():
            return
            
        # 現在処理中のファイルがあれば表示
        if hasattr(self, 'current_archive') and self.current_archive:
            ext = os.path.splitext(self.current_archive)[1].lower()
            if ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
                try:
                    self.update_processing_image(self.current_archive)
                    return
                except Exception as e:
                    self.log_error(f"プレビュー更新エラー: {e}")
                    
        # 処理中ファイルがないか、更新に失敗した場合
        self.image_canvas.delete("all")
        self.image_info_label.config(text="表示可能な処理中画像はありません")
        self.current_processing_path = None
        self.current_processing_photo = None

    def toggle_pause_action(self):
        """処理の一時停止/再開を切り替え"""
        if not self.processing:
            return
        
        self.pause_processing = not self.pause_processing
        
        if self.pause_processing:
            self.pause_button.config(text="再開", bg="#FFCC00")
            self.log("処理を一時停止しました")
        else:
            self.pause_button.config(text="一時停止", bg="#FFCC66")
            self.log("処理を再開しました")

    # 中止確認ダイアログ
    def confirm_cancel(self):
        """処理中止の確認"""
        if not self.processing:
            return
        
        result = messagebox.askquestion(
            "処理中止の確認", 
            "現在の処理を中止してもよろしいですか？\n\n注意: 現在処理中のファイルは完了まで待機します。",
            icon='warning'
        )
        
        if result == 'yes':
            self.cancel_processing = True
            self.log("処理を中止します。現在のファイル処理完了後に停止します...")
            self.execute_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.DISABLED)
            self.cancel_button.config(state=tk.DISABLED)

    # 画像表示を更新するメソッド
    def update_processing_image(self, image_path):
        """処理中の画像を表示エリアに更新"""
        # プレビューが無効な場合は何もしない
        if not hasattr(self, 'preview_enabled') or not self.preview_enabled.get():
            return
            
        if not image_path or not os.path.exists(image_path):
            # 画像がない場合は表示をクリア
            self.image_canvas.delete("all")
            self.image_info_label.config(text=LANG["no_image_processing"])
            self.current_processing_path = None
            self.current_processing_photo = None
            return
            
        # 既に同じ画像を表示中なら更新しない
        if self.current_processing_path == image_path:
            return
            
        try:
            # 画像をロード
            img = Image.open(image_path)
            
            # キャンバスサイズに合わせてリサイズ
            canvas_width = self.image_canvas.winfo_width()
            canvas_height = self.image_canvas.winfo_height()
            
            # 幅または高さが0の場合（初期化時など）はデフォルト値を使用
            if canvas_width <= 1 or canvas_height <= 1:
                canvas_width = 280
                canvas_height = 280
                
            # 画像のアスペクト比を維持
            img_width, img_height = img.size
            ratio = min(canvas_width / img_width, canvas_height / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            
            # 画像をリサイズ
            img_resized = img.resize((new_width, new_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img_resized)
            
            # キャンバスをクリアして新しい画像を表示
            self.image_canvas.delete("all")
            self.image_canvas.create_image(canvas_width/2, canvas_height/2, image=photo, anchor=tk.CENTER)
            
            # PhotoImageオブジェクトの参照を保持（ガベージコレクション対策）
            self.current_processing_photo = photo
            self.current_processing_path = image_path
            
            # 画像情報を表示
            filesize = os.path.getsize(image_path)
            basename = os.path.basename(image_path)
            info_text = f"ファイル: {basename}\nサイズ: {self.format_size(filesize)}\n解像度: {img_width}×{img_height}"
            self.image_info_label.config(text=info_text)
            
        except Exception as e:
            self.log_error(f"画像表示エラー: {e}")
            self.image_canvas.delete("all")
            self.image_info_label.config(text=f"画像表示エラー: {os.path.basename(image_path)}")

    # --- 高度な設定タブ（追加） ---
    def create_advanced_tab(self, parent):
        """並列処理などの高度な設定タブを作成"""
        # 並列処理設定
        frame_parallel = ttk.LabelFrame(parent, text=LANG["parallel_settings"])
        frame_parallel.pack(fill=tk.X, padx=5, pady=5)
        
        # 最大ワーカー数
        tk.Label(frame_parallel, text=LANG["max_workers"]).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        tk.Scale(frame_parallel, from_=1, to=32, orient=tk.HORIZONTAL, variable=self.max_workers).grid(row=0, column=1, sticky="we", padx=5, pady=5)
        
        # バッチサイズ
        tk.Label(frame_parallel, text=LANG["batch_size"]).grid(row=1, column=0, sticky="e", padx=5, pady=5)
        tk.Scale(frame_parallel, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.batch_size).grid(row=1, column=1, sticky="we", padx=5, pady=5)
        
        
        # 一時ディレクトリ
        frame_temp = ttk.LabelFrame(parent, text=LANG["temp_dir"])
        frame_temp.pack(fill=tk.X, padx=5, pady=5)
        tk.Entry(frame_temp, textvariable=self.temp_dir_var, width=50).pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
        tk.Button(frame_temp, text=LANG["browse"], command=self.select_temp_dir).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(frame_temp, text="中身をクリア", command=self.clear_temp_dir,
                  bg="#ffe0e0").pack(side=tk.LEFT, padx=5, pady=5)

        # メンテナンス: 元ファイル移動先のクリア
        frame_maint = ttk.LabelFrame(parent, text="メンテナンス")
        frame_maint.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_maint,
                 text="一時フォルダや元ファイル移動先を空にしたいときに使用します。"
                      "\n※処理中は実行できません。"
                 ).pack(anchor="w", padx=5, pady=(5, 0))
        btn_row = tk.Frame(frame_maint)
        btn_row.pack(anchor="w", padx=5, pady=5)
        tk.Button(btn_row, text="一時フォルダの中身を削除",
                  command=self.clear_temp_dir, bg="#ffe0e0").pack(side=tk.LEFT, padx=2)
        tk.Button(btn_row, text="元ファイル移動先の中身を削除",
                  command=self.clear_backup_folder, bg="#ffe0e0").pack(side=tk.LEFT, padx=2)

        # テスト出力設定フレーム（新規追加）
        frame_test_output = ttk.LabelFrame(parent, text=LANG["test_output_settings"])
        frame_test_output.pack(fill=tk.X, padx=5, pady=5)
        
        # テスト出力有効/無効チェックボックス
        tk.Checkbutton(frame_test_output, text=LANG["use_test_output"], 
                      variable=self.use_test_output).pack(anchor="w", padx=5, pady=2)
        
        # テスト出力先フォルダ設定
        test_folder_frame = tk.Frame(frame_test_output)
        test_folder_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(test_folder_frame, text=LANG["test_output_folder"]).pack(side=tk.LEFT)
        tk.Entry(test_folder_frame, textvariable=self.test_output_folder, width=40).pack(side=tk.LEFT, padx=5)
        tk.Button(test_folder_frame, text=LANG["browse"], command=self.select_test_output_folder).pack(side=tk.LEFT)

    def _clear_directory_contents(self, target_dir, label):
        """target_dir の中身（直下ファイル・サブフォルダ）を削除する。target_dir 自体は残す。"""
        if self.processing:
            messagebox.showwarning(label, "処理中は実行できません。完了/中止後に再度お試しください。")
            return False
        if not target_dir:
            messagebox.showwarning(label, "対象フォルダが設定されていません。")
            return False
        if not os.path.isdir(target_dir):
            messagebox.showwarning(label, f"フォルダが見つかりません:\n{target_dir}")
            return False
        if not messagebox.askyesno(label,
                                   f"以下のフォルダの中身をすべて削除します。よろしいですか？\n\n{target_dir}"):
            return False
        errors = []
        removed = 0
        try:
            for entry in os.listdir(target_dir):
                p = os.path.join(target_dir, entry)
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                    removed += 1
                except Exception as e:
                    errors.append(f"{entry}: {e}")
        except Exception as e:
            errors.append(str(e))
        msg = f"{removed}件削除しました。"
        if errors:
            msg += f"\n\n削除できなかった項目:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n…他 {len(errors) - 10} 件"
            messagebox.showwarning(label, msg)
        else:
            messagebox.showinfo(label, msg)
        self.log(f"[{label}] {target_dir} の中身を {removed} 件削除（エラー {len(errors)} 件）")
        return True

    def clear_temp_dir(self):
        """一時ディレクトリの中身を削除する。"""
        self._clear_directory_contents(self.temp_dir_var.get() or self.temp_dir, "一時フォルダのクリア")

    def clear_backup_folder(self):
        """元ファイル移動先の中身を削除する。"""
        self._clear_directory_contents(self.original_backup_folder.get(), "元ファイル移動先のクリア")

    def select_temp_dir(self):
        """一時ディレクトリを選択"""
        if self.processing:
            return
            
        folder = filedialog.askdirectory(title="一時ディレクトリを選択")
        if folder:
            self.temp_dir_var.set(folder)
            # 自動作成した一時ディレクトリのみ削除
            if self._current_temp_managed and os.path.exists(self.temp_dir) and self.temp_dir != folder:
                managed_path = self.temp_dir
                try:
                    shutil.rmtree(managed_path)
                except Exception:
                    pass
                if not os.path.exists(managed_path):
                    self._managed_temp_dirs.discard(managed_path)
            # 新しい一時ディレクトリを設定
            self.temp_dir = folder
            self._current_temp_managed = False
            # 必要に応じて作成するが、ユーザー指定なので後で削除しない
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)

    def select_test_output_folder(self):
        """テスト出力先フォルダを選択"""
        if self.processing:
            return
            
        folder = filedialog.askdirectory(title="テスト出力先フォルダを選択")
        if folder:
            self.test_output_folder.set(folder)
            self.log(f"テスト出力先: {folder}")
            
            # フォルダが存在しない場合は作成
            if not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                    self.log(f"テスト出力先フォルダを作成しました: {folder}")
                except Exception as e:
                    self.log_error(f"テスト出力先フォルダ作成エラー: {e}")

    # 時間表示を更新するための新しいメソッド
    def update_time_info(self):
        """処理時間情報を更新する"""
        if not self.processing or not self.start_time:
            return
        
        # 経過時間計算
        elapsed_seconds = time.time() - self.start_time
        elapsed_formatted = self.format_time(elapsed_seconds)
        
        # 処理比率の更新（実書籍数ベース、未設定時は入力数）
        total_files = self.total_count if self.total_count > 0 else len(self.input_files)
        self.processing_ratio_label.config(text=f"処理済み: {self.processed_count}/{total_files}")

        # 残り時間計算
        if self.processed_count > 0:
            avg_time_per_file = elapsed_seconds / self.processed_count
            remaining_files = max(0, total_files - self.processed_count)
            estimated_remaining_seconds = avg_time_per_file * remaining_files
            remaining_formatted = self.format_time(estimated_remaining_seconds)
            self.remaining_time_label.config(text=f"残り時間: {remaining_formatted}")
        else:
            self.remaining_time_label.config(text="残り時間: 計算中...")
        
        # 経過時間更新
        self.elapsed_time_label.config(text=f"経過時間: {elapsed_formatted}")
        
        # 1秒ごとに更新
        if self.processing:
            self.after(1000, self.update_time_info)

    # 時間のフォーマット用ヘルパーメソッド
    def format_time(self, seconds):
        """秒数を時:分:秒の形式にフォーマット"""
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def update_memory_usage(self, force_update=False):
        """CPU・メモリ使用量を定期的に更新"""
        try:
            # 静的変数で前回の更新時刻を管理
            current_time = time.time()
            if not hasattr(self, "_last_resource_update"):
                self._last_resource_update = 0
            
            # 1秒間隔でのみ更新（または強制更新時）
            if force_update or (current_time - self._last_resource_update >= 1.0):
                process = psutil.Process(os.getpid())
                
                # メモリ使用量を取得
                memory_mb = process.memory_info().rss / (1024 * 1024)
                self.memory_label.config(text=f"メモリ使用量: {memory_mb:.1f}MB")
                
                # CPU使用率を取得（新規追加）
                cpu_percent = process.cpu_percent(interval=0.1)  # 0.1秒のサンプリングで測定
                self.cpu_label.config(text=f"CPU使用率: {cpu_percent:.1f}%")
                
                # CPU使用率の値に応じてラベルの色を変更
                if cpu_percent > 80:
                    self.cpu_label.config(fg="#CC0000")  # 高負荷時は赤
                elif cpu_percent > 50:
                    self.cpu_label.config(fg="#CC6600")  # 中負荷時はオレンジ
                else:
                    self.cpu_label.config(fg="#009900")  # 低負荷時は緑
                
                self._last_resource_update = current_time
        except Exception as e:
            self.memory_label.config(text="メモリ使用量: 不明")
            self.cpu_label.config(text="CPU使用率: 不明")
        
        # 次回の更新をスケジュール
        self.after(1000, self.update_memory_usage)

    # エラーメッセージを日本語化する関数を追加
    def translate_error(self, error_message):
        """エラーメッセージを日本語化"""
        if not error_message:
            return "不明なエラー"
        
        # 英語のエラーメッセージを日本語に変換
        for eng, jpn in ERROR_TRANSLATIONS.items():
            if eng in error_message:
                return error_message.replace(eng, jpn)
        
        return error_message  # 該当する翻訳がなければ元のメッセージを返す

    def get_optimal_workers(self):
        """システム状態に基づいて最適なワーカー数を決定"""
        try:
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / (1024 * 1024)
            
            # CPU数の取得とUIスレッド用に2コア確保
            cpu_count = os.cpu_count() or 24
            ui_reserved_cores = 2  # UIスレッド用に予約するコア数
            available_cores = max(1, cpu_count - ui_reserved_cores)
            
            # システム全体の負荷を考慮
            system_load = psutil.cpu_percent(interval=0.1) / 100.0
            if system_load > 0.7:  # 70%以上の負荷
                available_cores = max(1, int(available_cores * 0.5))
            
            # メモリ使用率に応じた調整
            available_memory = 64 * 1024 - memory_mb
            
            if available_memory > 32 * 1024:  # 32GB以上空き
                return min(self.max_workers.get(), available_cores)
            elif available_memory > 16 * 1024:  # 16GB以上空き
                return min(self.max_workers.get(), int(available_cores * 0.75))
            elif available_memory > 8 * 1024:  # 8GB以上空き
                return min(self.max_workers.get(), int(available_cores * 0.5))
            else:
                return min(self.max_workers.get(), max(1, int(available_cores * 0.25)))
        except:
            # エラー時は控えめな値
            return min(self.max_workers.get(), 4)

    # ファイルリストボックスの右クリックメニュー
    def show_listbox_menu(self, event):
        if not self.file_tree.selection():
            return
            
        menu = Menu(self, tearoff=0)
        menu.add_command(label=LANG["menu_delete"], command=self.delete_selected_files)
        menu.add_command(label=LANG["menu_select_all"], command=self.select_all_files)
        menu.add_separator()
        menu.add_command(label=LANG["menu_delete_all"], command=self.delete_all_files)
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def delete_selected_files(self):
        """選択されたファイルを削除"""
        if self.processing:
            return
        targets = self._selected_top_paths()
        if not targets:
            return

        if messagebox.askyesno(LANG["confirm_delete"], LANG["confirm_delete_msg"]):
            for iid, path in targets:
                for child in self.file_tree.get_children(iid):
                    cp = self._tree_path_by_item.pop(child, None)
                    if cp:
                        self._tree_item_by_path.pop(cp, None)
                self.file_tree.delete(iid)
                self._tree_item_by_path.pop(path, None)
                self._tree_path_by_item.pop(iid, None)
                if path in self.input_files:
                    self.input_files.remove(path)
            self.update_file_count()

    def select_all_files(self):
        """すべてのファイルを選択（トップレベルのみ）"""
        for iid in self.file_tree.get_children():
            self.file_tree.selection_add(iid)

    def delete_all_files(self):
        """すべてのファイルを削除"""
        if self.processing:
            return

        if messagebox.askyesno(LANG["confirm_delete"], LANG["confirm_delete_msg"]):
            self._tree_clear_all()
            self.input_files.clear()
            self.update_file_count()

    # テスト圧縮機能
    def test_compression(self):
        """拡張されたテスト圧縮を実行"""
        if not self.input_files:
            messagebox.showwarning(LANG["error"], LANG["no_input"])
            return
        
        # テスト用ダイアログを作成
        test_dialog = tk.Toplevel(self)
        test_dialog.title("テスト圧縮")
        test_dialog.geometry("600x500")
        test_dialog.minsize(500, 400)
        test_dialog.transient(self)
        test_dialog.grab_set()
        
        # メインフレーム
        main_frame = tk.Frame(test_dialog, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # タイトル
        tk.Label(main_frame, text="テスト圧縮", font=("", 14, "bold")).pack(pady=(0, 10))
        
        # ファイル選択フレーム
        file_frame = tk.LabelFrame(main_frame, text="テスト対象ファイル")
        file_frame.pack(fill=tk.X, pady=5)
        
        # ファイル選択コンボボックス
        test_files = []
        for f in self.input_files:
            ext = os.path.splitext(f)[1].lower()
            if ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
                test_files.append(os.path.basename(f))
        
        if not test_files:
            test_files = ["テスト可能な画像ファイルがありません"]
        
        file_var = tk.StringVar(value=test_files[0] if test_files else "")
        file_combo = ttk.Combobox(file_frame, textvariable=file_var, values=test_files, state="readonly", width=40)
        file_combo.pack(padx=10, pady=10)
        
        # 結果表示フレーム
        result_frame = tk.LabelFrame(main_frame, text="テスト結果")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 左側: 元画像表示
        left_frame = tk.Frame(result_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tk.Label(left_frame, text="元画像").pack()
        
        orig_canvas = tk.Canvas(left_frame, bg="#f0f0f0", width=200, height=200)
        orig_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        orig_info = tk.Label(left_frame, text="元サイズ: -")
        orig_info.pack()
        
        # 右側: 圧縮後画像表示
        right_frame = tk.Frame(result_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tk.Label(right_frame, text="圧縮後").pack()
        
        comp_canvas = tk.Canvas(right_frame, bg="#f0f0f0", width=200, height=200)
        comp_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        comp_info = tk.Label(right_frame, text="圧縮後: -")
        comp_info.pack()
        
        # 結果サマリー
        summary_frame = tk.Frame(main_frame)
        summary_frame.pack(fill=tk.X, pady=5)
        
        result_label = tk.Label(summary_frame, text="", font=("", 12))
        result_label.pack()
        
        # 実行ボタン
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 現在の画像と圧縮後画像の参照
        test_dialog.orig_photo = None
        test_dialog.comp_photo = None
        test_dialog.test_file_path = None
        
        # 実行処理
        def execute_test():
            # 選択したファイル名から完全パスを取得
            selected_file = file_var.get()
            if selected_file == "テスト可能な画像ファイルがありません":
                return
            
            full_path = None
            for f in self.input_files:
                if os.path.basename(f) == selected_file:
                    full_path = f
                    break
            
            if not full_path:
                return
            
            test_dialog.test_file_path = full_path
            test_button.config(state=tk.DISABLED, text="処理中...")
            result_label.config(text="処理中...", fg="blue")
            
            # 別スレッドでテスト処理を実行
            threading.Thread(target=lambda: perform_test(full_path), daemon=True).start()
        
        def perform_test(file_path):
            try:
                # 元画像を表示
                display_original_image(file_path)
                
                # テスト圧縮を実行
                orig_size = os.path.getsize(file_path)
                orig_info.config(text=f"元サイズ: {self.format_size(orig_size)}")
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    tmpfile = os.path.join(temp_dir, os.path.basename(file_path))
                    shutil.copy2(file_path, tmpfile)
                    
                    # リサイズ処理
                    resized_path = maybe_resize(tmpfile, self.resize_mode.get(), self.resize_width.get(), 
                                              self.resize_height.get(), LANG["resize_modes"])
                    
                    # 圧縮処理
                    compressed_dir = os.path.join(temp_dir, "compressed")
                    os.makedirs(compressed_dir, exist_ok=True)
                    
                    # パラメータ準備
                    params = {
                        'jpeg_quality': self.jpeg_quality.get(),
                        'jpeg_progressive': self.jpeg_progressive.get(),
                        'jpeg_keep_metadata': self.jpeg_keep_metadata.get(),
                        'png_compression_level': self.png_compression_level.get(),
                        'png_keep_metadata': self.png_keep_metadata.get(),
                        'webp_quality': self.webp_quality.get(),
                        'webp_keep_metadata': self.webp_keep_metadata.get(),
                        'tiff_keep_metadata': self.tiff_keep_metadata.get(),
                        'resize_mode': self.resize_mode.get(),
                        'resize_width': self.resize_width.get(),
                        'resize_height': self.resize_height.get(),
                        'resize_modes': LANG["resize_modes"],
                        'skip_if_larger': self.skip_if_larger.get(),
                        'file_suffix': self.file_suffix.get(),
                        'base_folder': temp_dir
                    }
                    
                    result = compress_image_worker(resized_path, compressed_dir, **params)
                    
                    if result[1]:  # 圧縮結果が存在する場合
                        compressed_file = result[1]
                        final_size = os.path.getsize(compressed_file)
                        reduction = (1 - final_size / orig_size) * 100
                        
                        # 圧縮後の画像を表示
                        display_compressed_image(compressed_file)
                        comp_info.config(text=f"圧縮後: {self.format_size(final_size)}")
                        
                        # 結果表示
                        test_dialog.after(0, lambda: result_label.config(
                            text=f"圧縮率: {reduction:.1f}% 削減 ({self.format_size(orig_size)} → {self.format_size(final_size)})",
                            fg="green" if reduction > 0 else "red"
                        ))
                    else:
                        # エラーの場合
                        test_dialog.after(0, lambda: result_label.config(
                            text=f"テスト失敗: {result[2]}", fg="red"
                        ))
            except Exception as e:
                # エラー表示
                test_dialog.after(0, lambda: result_label.config(
                    text=f"エラー: {e}", fg="red"
                ))
            finally:
                # ボタンを有効に戻す
                test_dialog.after(0, lambda: test_button.config(state=tk.NORMAL, text="テスト実行"))
        
        def display_original_image(file_path):
            try:
                img = Image.open(file_path)
                width, height = img.size
                
                # キャンバスサイズに合わせてリサイズ
                canvas_width = orig_canvas.winfo_width()
                canvas_height = orig_canvas.winfo_height()
                
                if canvas_width <= 1:
                    canvas_width = 200
                if canvas_height <= 1:
                    canvas_height = 200
                
                # アスペクト比を維持
                ratio = min(canvas_width / width, canvas_height / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                
                # 画像のリサイズ
                img_resized = img.resize((new_width, new_height), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img_resized)
                
                # キャンバスに表示
                orig_canvas.delete("all")
                orig_canvas.create_image(canvas_width/2, canvas_height/2, image=photo, anchor=tk.CENTER)
                
                # 参照の保持
                test_dialog.orig_photo = photo
                
            except Exception as e:
                print(f"Original image display error: {e}")
        
        def display_compressed_image(file_path):
            try:
                img = Image.open(file_path)
                width, height = img.size
                
                # キャンバスサイズに合わせてリサイズ
                canvas_width = comp_canvas.winfo_width()
                canvas_height = comp_canvas.winfo_height()
                
                if canvas_width <= 1:
                    canvas_width = 200
                if canvas_height <= 1:
                    canvas_height = 200
                
                # アスペクト比を維持
                ratio = min(canvas_width / width, canvas_height / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                
                # 画像のリサイズ
                img_resized = img.resize((new_width, new_height), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img_resized)
                
                # キャンバスに表示
                comp_canvas.delete("all")
                comp_canvas.create_image(canvas_width/2, canvas_height/2, image=photo, anchor=tk.CENTER)
                
                # 参照の保持
                test_dialog.comp_photo = photo
                
            except Exception as e:
                print(f"Compressed image display error: {e}")
        
        # キャンバスのリサイズイベント
        def on_canvas_resize(event):
            if test_dialog.test_file_path:
                display_original_image(test_dialog.test_file_path)
        
        orig_canvas.bind("<Configure>", on_canvas_resize)
        
        # 実行ボタン
        test_button = tk.Button(button_frame, text="テスト実行", command=execute_test)
        test_button.pack(side=tk.LEFT, padx=5)
        
        # 閉じるボタン
        close_button = tk.Button(button_frame, text="閉じる", command=test_dialog.destroy)
        close_button.pack(side=tk.RIGHT, padx=5)
        
        # ウィンドウが表示されるまで待機し、キャンバスサイズが確定してから画像を表示
        test_dialog.update_idletasks()
        
        # ファイル選択が変更されたらプレビュー更新
        def on_file_change(event):
            selected_file = file_var.get()
            if selected_file == "テスト可能な画像ファイルがありません":
                return
                
            for f in self.input_files:
                if os.path.basename(f) == selected_file:
                    display_original_image(f)
                    test_dialog.test_file_path = f
                    orig_size = os.path.getsize(f)
                    orig_info.config(text=f"元サイズ: {self.format_size(orig_size)}")
                    # 圧縮結果をクリア
                    comp_canvas.delete("all")
                    comp_info.config(text="圧縮後: -")
                    result_label.config(text="")
                    break
        
        file_combo.bind("<<ComboboxSelected>>", on_file_change)
        
        # 初期ファイル表示
        if test_files and test_files[0] != "テスト可能な画像ファイルがありません":
            # 初期選択されたファイルを表示
            for f in self.input_files:
                if os.path.basename(f) == test_files[0]:
                    test_dialog.after(100, lambda f=f: display_original_image(f))
                    test_dialog.test_file_path = f
                    orig_size = os.path.getsize(f)
                    orig_info.config(text=f"元サイズ: {self.format_size(orig_size)}")
                    break

    def execute_test_compression(self, test_file):
        """テスト圧縮の実行処理"""
        self.log(f"テスト圧縮を実行: {test_file}")
        orig_size = os.path.getsize(test_file)
        
        # 画像を表示
        self.run_on_ui_thread(self.update_processing_image, test_file)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            tmpfile = os.path.join(temp_dir, os.path.basename(test_file))
            shutil.copy2(test_file, tmpfile)
            
            try:
                # リサイズ処理
                resized_path = maybe_resize(tmpfile, self.resize_mode.get(), self.resize_width.get(), 
                                          self.resize_height.get(), LANG["resize_modes"])
                
                # 圧縮処理
                compressed_dir = os.path.join(temp_dir, "compressed")
                os.makedirs(compressed_dir, exist_ok=True)
                
                # パラメータ準備
                params = {
                    'jpeg_quality': self.jpeg_quality.get(),
                    'jpeg_progressive': self.jpeg_progressive.get(),
                    'jpeg_keep_metadata': self.jpeg_keep_metadata.get(),
                    'png_compression_level': self.png_compression_level.get(),
                    'png_keep_metadata': self.png_keep_metadata.get(),
                    'webp_quality': self.webp_quality.get(),
                    'webp_keep_metadata': self.webp_keep_metadata.get(),
                    'tiff_keep_metadata': self.tiff_keep_metadata.get(),
                    'resize_mode': self.resize_mode.get(),
                    'resize_width': self.resize_width.get(),
                    'resize_height': self.resize_height.get(),
                    'resize_modes': LANG["resize_modes"],
                    'skip_if_larger': self.skip_if_larger.get(),
                    'file_suffix': self.file_suffix.get(),
                    'base_folder': temp_dir
                }
                
                result = compress_image_worker(resized_path, compressed_dir, **params)
                
                if result[1]:  # 出力パスがある場合
                    compressed_file = result[1]
                    final_size = os.path.getsize(compressed_file)
                    reduction = (1 - final_size / orig_size) * 100
                    
                    # 圧縮後の画像を表示
                    self.run_on_ui_thread(self.update_processing_image, compressed_file)
                    
                    result_msg = (
                        f"テスト圧縮結果:\n"
                        f"元ファイル: {self.format_size(orig_size)}\n"
                        f"圧縮後: {self.format_size(final_size)}\n"
                        f"削減率: {reduction:.1f}%"
                    )
                    
                    if result[2]:  # 警告メッセージがある場合
                        result_msg += f"\n\n注意: {result[2]}"
                    
                    self.log(result_msg)
                    messagebox.showinfo("テスト結果", result_msg)
                else:
                    self.log_error(f"テスト圧縮失敗: {result[2]}")
                    messagebox.showerror(LANG["error"], f"テスト圧縮失敗: {result[2]}")
                    
            except Exception as e:
                self.log_error(f"テスト圧縮中にエラーが発生しました: {e}")
                messagebox.showerror(LANG["error"], f"テスト圧縮中にエラーが発生しました: {e}")
            
            finally:
                # 終了時に表示をクリア
                self.run_on_ui_thread(self.update_processing_image, None)

    # アプリケーションについて
    def show_about(self):
        """アプリケーション情報を表示"""
        messagebox.showinfo("About", LANG["about_text"])

    # 依存関係チェック
    def check_dependencies(self):
        """依存関係のチェック"""
        missing = []
        
        # 7-Zip
        if not self.has_7z:
            missing.append("7-Zip (RAR処理に必要)")
            
        # Caesium CLT
        if not self.check_caesium_clt():
            missing.append("Caesium CLT (必須)")
            
        # 結果表示
        if missing:
            result = "以下の依存関係が見つかりません:\n" + "\n".join(missing)
        else:
            result = "すべての依存関係が正常にインストールされています。"
            
        messagebox.showinfo(LANG["check_deps"], result)

    # 履歴管理関連のメソッド
    def load_history(self):
        """履歴ファイルを読み込む"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.log_error(f"履歴ファイル読み込みエラー: {e}")
        return []

    def save_history(self):
        """履歴をファイルに保存"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_error(f"履歴ファイル保存エラー: {e}")

    def show_history(self):
        """拡張された履歴表示ウィンドウを表示"""
        # 追加: 履歴データを最新化
        self.history = self.load_history()
        
        history_window = tk.Toplevel(self)
        history_window.title("処理履歴")
        history_window.geometry("1000x700")  # ウィンドウサイズ拡大
        history_window.minsize(800, 600)
        
        # ウィンドウアイコン設定（可能な場合）
        try:
            history_window.iconbitmap("icon.ico")  # アイコンファイルがある場合
        except:
            pass
        
        # メインフレーム
        main_frame = tk.Frame(history_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # ヘッダーフレーム
        header_frame = tk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(header_frame, text="処理履歴", font=("", 16, "bold")).pack(side=tk.LEFT)
        
        # 右側にフィルターコントロール
        filter_frame = tk.Frame(header_frame)
        filter_frame.pack(side=tk.RIGHT)
        
        # 検索フレーム
        search_frame = tk.Frame(filter_frame)
        search_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        tk.Label(search_frame, text="検索:").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)
        
        # 日付フィルターフレーム
        date_frame = tk.Frame(filter_frame)
        date_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        tk.Label(date_frame, text="日付フィルター:").pack(side=tk.LEFT)
        date_filter_var = tk.StringVar(value="すべて")
        date_filter = ttk.Combobox(date_frame, textvariable=date_filter_var, values=["すべて", "今日", "昨日", "過去7日", "過去30日"])
        date_filter.pack(side=tk.LEFT, padx=5)
        date_filter.config(state="readonly")
        
        # メインコンテンツフレーム - 左右分割
        content_frame = tk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左側：履歴リスト
        list_frame = tk.LabelFrame(content_frame, text="履歴リスト")
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # スクロールバー
        list_scrollbar = tk.Scrollbar(list_frame)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 履歴リストには列ヘッダーを追加（Treeviewウィジェット使用）
        history_list = ttk.Treeview(list_frame, columns=("date", "files", "ratio"), show="headings")
        history_list.heading("date", text="日時")
        history_list.heading("files", text="ファイル数")
        history_list.heading("ratio", text="圧縮率")
        
        history_list.column("date", width=150)
        history_list.column("files", width=80)
        history_list.column("ratio", width=80)
        
        history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # スクロールバー連動
        list_scrollbar.config(command=history_list.yview)
        history_list.config(yscrollcommand=list_scrollbar.set)
        
        # 右側：詳細表示とグラフ
        detail_frame = tk.Frame(content_frame)
        detail_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # 上部：詳細情報
        detail_label_frame = tk.LabelFrame(detail_frame, text="詳細情報")
        detail_label_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        detail_scrollbar = tk.Scrollbar(detail_label_frame)
        detail_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        detail_text = tk.Text(detail_label_frame, wrap=tk.WORD)
        detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_text.config(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.config(command=detail_text.yview)
        
        # 詳細テキストのスタイル設定
        detail_text.tag_configure("heading", font=("", 12, "bold"))
        detail_text.tag_configure("subheading", font=("", 10, "bold"))
        detail_text.tag_configure("normal", font=("", 9))
        detail_text.tag_configure("success", foreground="green")
        detail_text.tag_configure("error", foreground="red")
        
        # 下部：グラフ表示フレーム
        graph_label_frame = tk.LabelFrame(detail_frame, text="統計情報")
        graph_label_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # タブ付きグラフ表示
        graph_notebook = ttk.Notebook(graph_label_frame)
        graph_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # タブ1: ファイル形式グラフ
        file_type_frame = tk.Frame(graph_notebook)
        graph_notebook.add(file_type_frame, text="ファイル形式")
        
        # タブ2: サイズ削減グラフ
        size_frame = tk.Frame(graph_notebook)
        graph_notebook.add(size_frame, text="サイズ削減")
        
        # タブ3: ファイル詳細
        files_frame = tk.Frame(graph_notebook)
        graph_notebook.add(files_frame, text="ファイル詳細")
        
        # ファイル詳細リスト
        files_scrollbar = tk.Scrollbar(files_frame)
        files_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        files_list = ttk.Treeview(
            files_frame, 
            columns=("name", "orig_size", "final_size", "ratio", "status"),
            show="headings"
        )
        files_list.heading("name", text="ファイル名")
        files_list.heading("orig_size", text="元サイズ")
        files_list.heading("final_size", text="圧縮後")
        files_list.heading("ratio", text="圧縮率")
        files_list.heading("status", text="状態")
        
        files_list.column("name", width=200)
        files_list.column("orig_size", width=80)
        files_list.column("final_size", width=80)
        files_list.column("ratio", width=60)
        files_list.column("status", width=80)
        
        files_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        files_scrollbar.config(command=files_list.yview)
        files_list.config(yscrollcommand=files_scrollbar.set)
        
        # 操作ボタンフレーム
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 更新ボタンの部分を修正（show_history関数内）
        refresh_button = tk.Button(
            button_frame, 
            text="更新", 
            command=lambda: self.refresh_history_display(history_list, date_filter_var.get(), search_var.get())
        )
        refresh_button.pack(side=tk.LEFT, padx=5)
        
        # エクスポートボタン
        export_button = tk.Button(
            button_frame, 
            text="CSV出力", 
            command=lambda: self.export_history_to_csv(history_list)
        )
        export_button.pack(side=tk.LEFT, padx=5)
        
        # 閉じるボタン
        close_button = tk.Button(button_frame, text="閉じる", command=history_window.destroy)
        close_button.pack(side=tk.RIGHT, padx=5)
        
        # 検索とフィルターの変更を監視
        search_entry.bind("<KeyRelease>", lambda e: self.populate_history_list_enhanced(
            history_list, date_filter_var.get(), search_var.get()
        ))
        
        date_filter.bind("<<ComboboxSelected>>", lambda e: self.populate_history_list_enhanced(
            history_list, date_filter_var.get(), search_var.get()
        ))
        
        # リスト選択時のイベント
        history_list.bind("<<TreeviewSelect>>", lambda e: self.show_history_detail_enhanced(
            history_list, detail_text, files_list, file_type_frame, size_frame
        ))
        
        # 初期データ表示
        self.populate_history_list_enhanced(history_list, "すべて", "")

    def refresh_history_display(self, treeview, date_filter, search_text):
        """履歴データを再読み込みして表示更新"""
        # 履歴を再読み込み
        self.history = self.load_history()
        # リストを更新
        self.populate_history_list_enhanced(treeview, date_filter, search_text)

    def populate_history_list_enhanced(self, treeview, date_filter="すべて", search_text=""):
        """拡張された履歴リスト表示機能"""
        # 既存アイテムをクリア
        for item in treeview.get_children():
            treeview.delete(item)
        
        # 日付フィルタリング用の基準日時
        now = datetime.datetime.now()
        today_start = datetime.datetime(now.year, now.month, now.day)
        yesterday_start = today_start - datetime.timedelta(days=1)
        week_ago = today_start - datetime.timedelta(days=7)
        month_ago = today_start - datetime.timedelta(days=30)
        
        # 履歴をフィルタリング
        filtered_history = []
        for entry in self.history:
            # 日付変換
            try:
                entry_date = datetime.datetime.strptime(entry["date"], "%Y-%m-%d %H:%M:%S")
            except:
                # 日付フォーマットが不正の場合はスキップ
                continue
            
            # 日付フィルター適用
            if date_filter == "今日" and entry_date < today_start:
                continue
            elif date_filter == "昨日" and (entry_date < yesterday_start or entry_date >= today_start):
                continue
            elif date_filter == "過去7日" and entry_date < week_ago:
                continue
            elif date_filter == "過去30日" and entry_date < month_ago:
                continue
            
            # 検索テキスト適用
            if search_text and search_text.lower() not in entry["date"].lower():
                # ファイル名検索（詳細な履歴がある場合）
                if "detailed_files" in entry:
                    found = False
                    for file_info in entry["detailed_files"]:
                        if search_text.lower() in file_info.get("name", "").lower():
                            found = True
                            break
                    if not found:
                        continue
                else:
                    continue
            
            filtered_history.append(entry)
        
        # 履歴をツリービューに追加
        for entry in filtered_history:
            # 圧縮率計算
            compression_ratio = 0
            if "size_summary" in entry:
                before = entry["size_summary"].get("before", 0)
                after = entry["size_summary"].get("after", 0)
                if before > 0:
                    compression_ratio = (1 - after / before) * 100
            
            # キャンセル済みの場合はマーク
            date_display = entry["date"]
            if entry.get("cancelled", False):
                date_display += " [中止]"
            
            # ツリービューに追加
            treeview.insert(
                "", "end", 
                values=(
                    date_display,
                    f"{entry.get('processed', 0)}/{entry.get('files', 0)}",
                    f"{compression_ratio:.1f}%"
                ),
                tags=("cancelled" if entry.get("cancelled", False) else "normal",)
            )
        
        # タグの設定
        treeview.tag_configure("cancelled", foreground="red")

    def show_history_detail_enhanced(self, treeview, detail_text, files_list, file_type_frame, size_frame):
        """選択された履歴の詳細情報とグラフを表示"""
        # 選択アイテム取得
        selection = treeview.selection()
        if not selection:
            return
        
        item_id = selection[0]
        item_index = treeview.index(item_id)
        
        # 対応する履歴エントリを取得
        if item_index >= len(self.history):
            return
        
        entry = self.history[item_index]
        
        # 詳細テキストをクリア
        detail_text.config(state=tk.NORMAL)
        detail_text.delete(1.0, tk.END)
        
        # 基本情報の表示
        detail_text.insert(tk.END, "処理概要\n", "heading")
        detail_text.insert(tk.END, f"日時: {entry['date']}\n", "normal")
        
        if entry.get("cancelled", False):
            detail_text.insert(tk.END, "状態: 途中で中止されました\n", "error")
        
        detail_text.insert(tk.END, f"ファイル数: {entry.get('files', 0)}\n", "normal")
        detail_text.insert(tk.END, f"処理完了: {entry.get('processed', 0)}\n", "normal")
        
        if "errors" in entry and entry["errors"] > 0:
            detail_text.insert(tk.END, f"エラー/スキップ: {entry['errors']}\n", "error")
        
        if "elapsed_time" in entry:
            elapsed = entry["elapsed_time"]
            detail_text.insert(tk.END, f"処理時間: {self.format_time(elapsed)}\n", "normal")
        
        # サイズ情報
        if "size_summary" in entry:
            detail_text.insert(tk.END, "\nサイズ情報\n", "subheading")
            before = entry["size_summary"].get("before", 0)
            after = entry["size_summary"].get("after", 0)
            
            detail_text.insert(tk.END, f"処理前合計: {self.format_size(before)}\n", "normal")
            detail_text.insert(tk.END, f"処理後合計: {self.format_size(after)}\n", "normal")
            
            if before > 0:
                ratio = (1 - after / before) * 100
                saved = before - after
                detail_text.insert(tk.END, f"削減率: {ratio:.1f}%\n", "success")
                detail_text.insert(tk.END, f"節約容量: {self.format_size(saved)}\n", "success")
        
        # 使用した設定
        if "settings" in entry:
            detail_text.insert(tk.END, "\n使用設定\n", "subheading")
            settings = entry["settings"]
            for key, value in settings.items():
                detail_text.insert(tk.END, f"  {key}: {value}\n", "normal")
        
        # ファイル形式の分布
        if "file_types" in entry:
            detail_text.insert(tk.END, "\nファイル形式分布\n", "subheading")
            for ext, count in entry["file_types"].items():
                if count > 0:
                    detail_text.insert(tk.END, f"  {ext}: {count}件\n", "normal")
        
        detail_text.config(state=tk.DISABLED)
        
        # ファイル詳細リスト
        self.populate_file_detail_list(files_list, entry)
        
        # グラフ表示
        self.draw_file_type_graph(file_type_frame, entry)
        self.draw_size_reduction_graph(size_frame, entry)

    def populate_file_detail_list(self, treeview, history_entry):
        """ファイル詳細リストを表示"""
        # 既存アイテムをクリア
        for item in treeview.get_children():
            treeview.delete(item)
        
        # 詳細なファイル情報がない場合
        if "detailed_files" not in history_entry:
            treeview.insert("", "end", values=("詳細情報なし", "", "", "", ""))
            return
        
        # ファイル詳細を表示
        for file_info in history_entry["detailed_files"]:
            name = file_info.get("name", "不明")
            orig_size = self.format_size(file_info.get("original_size", 0))
            
            if file_info.get("skipped", False):
                final_size = "-"
                ratio = "-"
                status = file_info.get("reason", "スキップ")
                tag = "error"
            else:
                final_size = self.format_size(file_info.get("final_size", 0))
                ratio = f"{file_info.get('compression_ratio', 0):.1f}%"
                status = "完了"
                tag = "success"
            
            item_id = treeview.insert("", "end", values=(name, orig_size, final_size, ratio, status))
            treeview.item(item_id, tags=(tag,))
        
        # タグの設定
        treeview.tag_configure("error", foreground="red")
        treeview.tag_configure("success", foreground="green")

    def draw_file_type_graph(self, frame, history_entry):
        """ファイル形式の分布を示す円グラフを描画"""
        # 既存のウィジェットをクリア
        for widget in frame.winfo_children():
            widget.destroy()
        
        # ファイル形式情報がない場合のチェック
        if "file_types" not in history_entry or not history_entry["file_types"]:
            tk.Label(frame, text="ファイル形式の統計情報がありません").pack(expand=True)
            return
        
        try:
            # matplotlib を動的にインポート
            import matplotlib
            matplotlib.use("TkAgg")  # バックエンドを設定
            
            # 日本語フォント設定
            matplotlib.rcParams['font.family'] = 'sans-serif'
            matplotlib.rcParams['font.sans-serif'] = ['MS Gothic', 'Yu Gothic', 'Meiryo', 'IPAGothic']
            matplotlib.rcParams['axes.unicode_minus'] = False
            
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            
            # データ準備
            file_types = history_entry["file_types"]
            
            # デバッグ情報をログに出力
            self.log(f"ファイル形式データ: {file_types}")
            
            labels = []
            sizes = []
            
            for ext, count in file_types.items():
                if count > 0:
                    # 先頭のドットを削除して表示
                    label = ext[1:] if ext.startswith(".") else ext
                    labels.append(label)
                    sizes.append(count)
            
            if not sizes:  # データがない場合
                tk.Label(frame, text="表示可能なファイル形式データがありません").pack(expand=True)
                return
            
            # グラフ作成
            fig = Figure(figsize=(5, 4), dpi=100)
            ax = fig.add_subplot(111)
            
            # カラーマップを設定
            colors = ['#3498db', '#2ecc71', '#e74c3c', '#f1c40f', '#9b59b6', '#1abc9c']
            
            # 円グラフ作成
            wedges, texts, autotexts = ax.pie(
                sizes, 
                labels=labels, 
                autopct='%1.1f%%', 
                startangle=90,
                colors=colors[:len(sizes)]
            )
            
            ax.axis('equal')  # 円グラフを円形に表示
            ax.set_title("ファイル形式の分布")
            
            # キャンバスにグラフを配置
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            
        except Exception as e:
            # エラー時の代替表示
            self.log_error(f"ファイル形式グラフエラー: {e}")
            msg_frame = tk.Frame(frame)
            msg_frame.pack(fill=tk.BOTH, expand=True)
            
            tk.Label(msg_frame, text=f"グラフ表示エラー: {e}").pack(pady=20)
            
            # 簡易的な表示
            for ext, count in file_types.items():
                if count > 0:
                    ext_label = ext[1:] if ext.startswith(".") else ext
                    tk.Label(msg_frame, text=f"{ext_label}: {count}件").pack()

    def draw_size_reduction_graph(self, frame, history_entry):
        """サイズ削減を示す棒グラフを描画（エラー・スキップ情報を含む）"""
        # 既存のウィジェットをクリア
        for widget in frame.winfo_children():
            widget.destroy()
        
        # サイズ情報がない場合
        if "size_summary" not in history_entry:
            tk.Label(frame, text="グラフ表示用のデータがありません").pack(expand=True)
            return
        
        try:
            # matplotlib を動的にインポート
            import matplotlib
            matplotlib.use("TkAgg")  # バックエンドを設定
            
            # 日本語フォント設定
            matplotlib.rcParams['font.family'] = 'sans-serif'
            matplotlib.rcParams['font.sans-serif'] = ['MS Gothic', 'Yu Gothic', 'Meiryo', 'IPAGothic']
            matplotlib.rcParams['axes.unicode_minus'] = False
            
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import numpy as np
            
            # データ準備
            before = history_entry["size_summary"].get("before", 0) / (1024 * 1024)  # MBに変換
            after = history_entry["size_summary"].get("after", 0) / (1024 * 1024)
            
            # エラー/スキップ情報
            error_count = history_entry.get("errors", 0)
            total_files = history_entry.get("files", 0)
            processed_files = history_entry.get("processed", 0)
            
            # 図の作成（2つのサブプロット）
            fig = Figure(figsize=(5, 4), dpi=100)
            
            # サブプロット1: サイズ比較（上部60%）
            ax1 = fig.add_subplot(211)
            labels = ['処理前', '処理後']
            sizes = [before, after]
            x = np.arange(len(labels))
            
            rects = ax1.bar(x, sizes, width=0.5)
            
            # グラフの装飾
            ax1.set_ylabel('サイズ (MB)')
            ax1.set_title('圧縮前後のサイズ比較')
            ax1.set_xticks(x)
            ax1.set_xticklabels(labels)
            
            # 削減率を表示
            reduction = (1 - after / before) * 100 if before > 0 else 0
            ax1.text(0.5, 0.95, f'削減率: {reduction:.1f}%', 
                    horizontalalignment='center', verticalalignment='center', 
                    transform=ax1.transAxes)
            
            # 実際の値を棒グラフ上に表示
            def autolabel(rects):
                for rect in rects:
                    height = rect.get_height()
                    ax1.annotate(f'{height:.1f}MB',
                                xy=(rect.get_x() + rect.get_width() / 2, height),
                                xytext=(0, 3),
                                textcoords="offset points",
                                ha='center', va='bottom')
            
            autolabel(rects)
            
            # サブプロット2: 処理状況（下部40%）
            ax2 = fig.add_subplot(212)
            
            # 処理状況データ
            success_count = processed_files - error_count
            status_labels = ['成功', 'エラー・スキップ']
            status_sizes = [success_count, error_count]
            
            # 円グラフで処理状況を表示
            if sum(status_sizes) > 0:  # データがある場合のみ
                colors = ['#66CC66', '#FF6666']  # 成功は緑系、エラーは赤系
                wedges, texts, autotexts = ax2.pie(status_sizes, labels=status_labels, 
                                                  autopct='%1.1f%%', startangle=90, 
                                                  colors=colors)
                ax2.axis('equal')
                ax2.set_title('処理結果の内訳')
                
                # 件数を凡例として表示
                ax2.legend([f'成功: {success_count}件', f'エラー・スキップ: {error_count}件'], 
                          loc='upper right')
            else:
                ax2.text(0.5, 0.5, "処理データなし", 
                        horizontalalignment='center', verticalalignment='center')
            
            # 全体のレイアウト調整
            fig.tight_layout()
            
            # キャンバスにグラフを配置
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            
        except Exception as e:
            # エラー時の代替表示
            self.log_error(f"サイズ削減グラフエラー: {e}")
            msg_frame = tk.Frame(frame)
            msg_frame.pack(fill=tk.BOTH, expand=True)
            
            tk.Label(msg_frame, text=f"グラフ表示エラー: {e}").pack(pady=10)
            
            # 簡易的な表示
            before = history_entry["size_summary"].get("before", 0)
            after = history_entry["size_summary"].get("after", 0)
            reduction = (1 - after / before) * 100 if before > 0 else 0
            
            tk.Label(msg_frame, text=f"処理前: {self.format_size(before)}").pack()
            tk.Label(msg_frame, text=f"処理後: {self.format_size(after)}").pack()
            tk.Label(msg_frame, text=f"削減率: {reduction:.1f}%").pack()
            
            # エラー・スキップ情報
            error_count = history_entry.get("errors", 0)
            total_files = history_entry.get("files", 0)
            processed_files = history_entry.get("processed", 0)
            
            tk.Label(msg_frame, text=f"処理成功: {processed_files - error_count}件").pack()
            tk.Label(msg_frame, text=f"エラー・スキップ: {error_count}件").pack()

    def export_history_to_csv(self, treeview):
        """履歴データをCSVファイルにエクスポート"""
        # 選択された項目を取得
        selections = treeview.selection()
        
        # エクスポートするデータの準備
        if selections:
            # 選択された項目のみエクスポート
            export_data = []
            for item_id in selections:
                item_index = treeview.index(item_id)
                if item_index < len(self.history):
                    export_data.append(self.history[item_index])
        else:
            # すべての履歴をエクスポート
            export_data = self.history
        
        if not export_data:
            messagebox.showinfo("エクスポート", "エクスポートするデータがありません")
            return
        
        # 保存先を選択
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="履歴をCSVとして保存"
        )
        
        if not file_path:
            return  # キャンセルされた場合
        
        try:
            import csv
            
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                # CSVヘッダー
                fieldnames = [
                    "日時", "ファイル数", "処理完了", "エラー/スキップ", 
                    "処理前サイズ(MB)", "処理後サイズ(MB)", "削減率(%)", 
                    "処理時間(秒)", "JPEG品質", "PNGレベル", "リサイズモード"
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                # 各履歴エントリを書き込み
                for entry in export_data:
                    # サイズ情報の計算
                    before = entry.get("size_summary", {}).get("before", 0) / (1024 * 1024)  # MBに変換
                    after = entry.get("size_summary", {}).get("after", 0) / (1024 * 1024)
                    ratio = (1 - after / before) * 100 if before > 0 else 0
                    
                    # 設定情報
                    settings = entry.get("settings", {})
                    
                    # CSVレコード作成
                    row = {
                        "日時": entry.get("date", ""),
                        "ファイル数": entry.get("files", 0),
                        "処理完了": entry.get("processed", 0),
                        "エラー/スキップ": entry.get("errors", 0),
                        "処理前サイズ(MB)": f"{before:.2f}",
                        "処理後サイズ(MB)": f"{after:.2f}",
                        "削減率(%)": f"{ratio:.2f}",
                        "処理時間(秒)": f"{entry.get('elapsed_time', 0):.2f}",
                        "JPEG品質": settings.get("jpeg_quality", ""),
                        "PNGレベル": settings.get("png_compression_level", ""),
                        "リサイズモード": settings.get("resize_mode", "")
                    }
                    
                    writer.writerow(row)
            
            messagebox.showinfo("エクスポート完了", f"履歴データを {file_path} に保存しました")
            
        except Exception as e:
            messagebox.showerror("エクスポートエラー", f"CSVファイル作成中にエラーが発生しました: {e}")

    def populate_history_list(self, listbox):
        """履歴リストにデータを表示"""
        listbox.delete(0, tk.END)
        for i, entry in enumerate(self.history):
            date = entry["date"]
            files = entry["files"]
            processed = entry.get("processed", 0)
            if "size_summary" in entry:
                before = self.format_size(entry["size_summary"]["before"])
                after = self.format_size(entry["size_summary"]["after"])
                ratio = 0
                if entry["size_summary"]["before"] > 0:
                    ratio = (1 - entry["size_summary"]["after"] / entry["size_summary"]["before"]) * 100
            else:
                before = "不明"
                after = "不明"
                ratio = 0
            
            listbox.insert(tk.END, f"{date} - {files}ファイル - 圧縮率:{ratio:.1f}%")

    def filter_history_list(self, listbox, search_text):
        """検索テキストに基づいて履歴リストをフィルタリング"""
        listbox.delete(0, tk.END)
        for i, entry in enumerate(self.history):
            date = entry["date"]
            text = f"{date} - {entry['files']}ファイル"
            if search_text.lower() in text.lower():
                files = entry["files"]
                processed = entry.get("processed", 0)
                if "size_summary" in entry:
                    before = self.format_size(entry["size_summary"]["before"])
                    after = self.format_size(entry["size_summary"]["after"])
                    ratio = 0
                    if entry["size_summary"]["before"] > 0:
                        ratio = (1 - entry["size_summary"]["after"] / entry["size_summary"]["before"]) * 100
                else:
                    before = "不明"
                    after = "不明"
                    ratio = 0
                
                listbox.insert(tk.END, f"{date} - {files}ファイル - 圧縮率:{ratio:.1f}%")

    def refresh_history_list(self, listbox):
        """履歴リストを更新"""
        self.history = self.load_history()
        self.populate_history_list(listbox)

    def show_history_detail(self, text_widget, history_entry):
        """選択された履歴の詳細情報を表示"""
        text_widget.config(state=tk.NORMAL)
        text_widget.delete(1.0, tk.END)
        
        text_widget.insert(tk.END, f"処理日時: {history_entry['date']}\n\n")
        text_widget.insert(tk.END, f"ファイル数: {history_entry['files']}\n")
        text_widget.insert(tk.END, f"処理完了: {history_entry.get('processed', 0)}\n")
        
        if "errors" in history_entry:
            text_widget.insert(tk.END, f"エラー/スキップ: {history_entry['errors']}\n")
        
        if "elapsed_time" in history_entry:
            elapsed = history_entry["elapsed_time"]
            text_widget.insert(tk.END, f"処理時間: {self.format_time(elapsed)}\n\n")
        
        if "size_summary" in history_entry:
            before = history_entry["size_summary"]["before"]
            after = history_entry["size_summary"]["after"]
            text_widget.insert(tk.END, f"圧縮前合計: {self.format_size(before)}\n")
            text_widget.insert(tk.END, f"圧縮後合計: {self.format_size(after)}\n")
            
            if before > 0:
                ratio = (1 - after / before) * 100
                saved = before - after
                text_widget.insert(tk.END, f"削減率: {ratio:.1f}%\n")
                text_widget.insert(tk.END, f"節約容量: {self.format_size(saved)}\n\n")
        
        if "settings" in history_entry:
            text_widget.insert(tk.END, "使用設定:\n")
            settings = history_entry["settings"]
            for key, value in settings.items():
                text_widget.insert(tk.END, f"  {key}: {value}\n")
        
        text_widget.config(state=tk.DISABLED)

    # 設定の保存と読み込み
    def save_config(self):
        """現在の設定をファイルに保存"""
        config = {
            "output_folder": self.output_folder.get(),
            "jpeg_quality": self.jpeg_quality.get(),
            "jpeg_progressive": self.jpeg_progressive.get(),
            "jpeg_keep_metadata": self.jpeg_keep_metadata.get(),
            "png_compression_level": self.png_compression_level.get(),
            "png_keep_metadata": self.png_keep_metadata.get(),
            "webp_quality": self.webp_quality.get(),
            "webp_keep_metadata": self.webp_keep_metadata.get(),
            "tiff_keep_metadata": self.tiff_keep_metadata.get(),
            "resize_mode": self.resize_mode.get(),
            "resize_width": self.resize_width.get(),
            "resize_height": self.resize_height.get(),
            "skip_if_larger": self.skip_if_larger.get(),
            "skip_already_processed": self.skip_already_processed.get(),
            "delete_original": self.delete_original.get(),
            "delete_original_mode": self.delete_original_mode.get(),
            "file_suffix": self.file_suffix.get(),
            # 高度な設定
            "max_workers": self.max_workers.get(),
            "batch_size": self.batch_size.get(),
            "temp_dir": self.temp_dir_var.get(),
            # プレビュー設定
            "preview_enabled": self.preview_enabled.get(),
            # テスト出力設定
            "use_test_output": self.use_test_output.get(),
            "test_output_folder": self.test_output_folder.get(),
            # 処理後自動置き換え設定
            "auto_replace_enabled": self.auto_replace_enabled.get(),
            "original_backup_folder": self.original_backup_folder.get(),
            # v2: 複数フォルダ構造は正常に処理されるため、移動設定は不要
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            messagebox.showinfo(LANG["settings"], "設定を保存しました。")
        except Exception as e:
            self.log_error(f"設定保存エラー: {e}")
            messagebox.showerror(LANG["error"], f"設定保存エラー: {e}")

    def load_config(self):
        """設定ファイルから設定を読み込む"""
        if not os.path.exists(self.config_file):
            # デフォルト設定を適用
            documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
            if os.path.exists(documents_dir):
                self.output_folder.set(os.path.join(documents_dir, "Compressed"))
            else:
                self.output_folder.set(os.path.join(os.path.expanduser("~"), "Compressed"))
            return
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # 設定を適用（パスが存在しなくても保存値を維持する）
            if "output_folder" in config and config["output_folder"]:
                self.output_folder.set(config["output_folder"])
            else:
                # 出力フォルダが存在しない場合はデフォルト値を設定
                documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
                if os.path.exists(documents_dir):
                    self.output_folder.set(os.path.join(documents_dir, "Compressed"))
                else:
                    self.output_folder.set(os.path.join(os.path.expanduser("~"), "Compressed"))
                    
            # タブ設定の読み込み
            self.jpeg_quality.set(config.get("jpeg_quality", 80))
            self.jpeg_progressive.set(config.get("jpeg_progressive", False))
            self.jpeg_keep_metadata.set(config.get("jpeg_keep_metadata", True))
            self.png_compression_level.set(config.get("png_compression_level", 3))
            self.png_keep_metadata.set(config.get("png_keep_metadata", True))
            self.webp_quality.set(config.get("webp_quality", 80))
            self.webp_keep_metadata.set(config.get("webp_keep_metadata", True))
            self.tiff_keep_metadata.set(config.get("tiff_keep_metadata", True))
            self.resize_mode.set(config.get("resize_mode", LANG["resize_modes"][0]))
            self.resize_width.set(config.get("resize_width", 0))
            self.resize_height.set(config.get("resize_height", 0))
            self.skip_if_larger.set(config.get("skip_if_larger", True))
            self.skip_already_processed.set(config.get("skip_already_processed", True))
            self.delete_original.set(config.get("delete_original", False))
            self.file_suffix.set(config.get("file_suffix", ""))
            if "delete_original_mode" in config: self.delete_original_mode.set(config.get("delete_original_mode", "trash"))
            
            # 高度な設定の読み込み
            self.max_workers.set(config.get("max_workers", 20))
            self.batch_size.set(config.get("batch_size", 50))
            
            # プレビュー設定の読み込み
            if "preview_enabled" in config:
                self.preview_enabled.set(config.get("preview_enabled", False))
            
            # テスト出力設定の読み込み
            if "use_test_output" in config:
                self.use_test_output.set(config.get("use_test_output", False))
            if "test_output_folder" in config:
                self.test_output_folder.set(config.get("test_output_folder", "G:\\ダウンロード"))
            # 処理後自動置き換え設定の読み込み
            if "auto_replace_enabled" in config:
                self.auto_replace_enabled.set(config.get("auto_replace_enabled", False))
            if "original_backup_folder" in config:
                self.original_backup_folder.set(config.get("original_backup_folder", ""))
            
            # v2: 複数フォルダ構造は正常に処理されるため、移動設定は不要
            
            # 一時ディレクトリ設定
            if "temp_dir" in config and os.path.exists(config["temp_dir"]):
                new_temp_dir = config["temp_dir"]
                old_temp_dir = self.temp_dir
                if self._current_temp_managed and os.path.exists(old_temp_dir) and old_temp_dir != new_temp_dir:
                    try:
                        shutil.rmtree(old_temp_dir)
                    except Exception:
                        pass
                    if not os.path.exists(old_temp_dir):
                        self._managed_temp_dirs.discard(old_temp_dir)
                self.temp_dir = new_temp_dir
                self._current_temp_managed = False
                self.temp_dir_var.set(new_temp_dir)
            
        except Exception as e:
            self.log_error(f"設定読み込みエラー: {e}")
            # エラー時はデフォルト値を設定
            documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
            if os.path.exists(documents_dir):
                self.output_folder.set(os.path.join(documents_dir, "Compressed"))
            else:
                self.output_folder.set(os.path.join(os.path.expanduser("~"), "Compressed"))

    # --- タブ: 出力 ---
    def create_output_tab(self, parent):
        frame_out = ttk.LabelFrame(parent, text=LANG["output_settings"])
        frame_out.pack(fill=tk.X, padx=5, pady=5)
        tk.Checkbutton(frame_out, text=LANG["skip_if_larger"], variable=self.skip_if_larger).pack(anchor="w", padx=5, pady=2)
        tk.Checkbutton(frame_out, text="処理済みマーカー付きのZIPはスキップ（再処理を避ける）",
                       variable=self.skip_already_processed).pack(anchor="w", padx=5, pady=2)
        
        # 元ファイル削除フレーム
        delete_frame = tk.Frame(frame_out)
        delete_frame.pack(anchor="w", padx=5, pady=2, fill=tk.X)
        tk.Checkbutton(delete_frame, text=LANG["delete_original"], variable=self.delete_original).pack(anchor="w", side=tk.LEFT)
        
        # 削除モード選択フレーム
        delete_mode_frame = tk.Frame(delete_frame)
        delete_mode_frame.pack(side=tk.LEFT, padx=20)
        tk.Radiobutton(delete_mode_frame, text="ゴミ箱に入れる", variable=self.delete_original_mode, value="trash").pack(anchor="w", side=tk.LEFT)
        tk.Radiobutton(delete_mode_frame, text="完全に削除", variable=self.delete_original_mode, value="permanent").pack(anchor="w", side=tk.LEFT, padx=10)
        
        frame_suffix = ttk.LabelFrame(parent, text=LANG["file_suffix"])
        frame_suffix.pack(fill=tk.X, padx=5, pady=5)
        tk.Entry(frame_suffix, textvariable=self.file_suffix, width=30).pack(side=tk.LEFT, padx=5, pady=5)
        
        # 処理後自動置き換えのUIは上部（出力先の右隣）に移動済み

    def _is_excluded_name(self, path):
        """パスの末尾コンポーネント名に除外パターンを含む場合 True。"""
        name = os.path.basename(path.rstrip("/\\"))
        for pat in self.excluded_name_patterns:
            if pat and pat in name:
                return True
        return False

    def _is_excluded_path(self, path, base=None):
        """パス全体（base からの相対パスの各コンポーネント）を除外パターンで判定。"""
        if base:
            try:
                rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
            except ValueError:
                rel = os.path.basename(path)
            parts = rel.replace("\\", "/").split("/")
        else:
            parts = [os.path.basename(path.rstrip("/\\"))]
        for part in parts:
            for pat in self.excluded_name_patterns:
                if pat and pat in part:
                    return True
        return False

    # ドラッグ＆ドロップイベント
    def on_drop_files(self, event):
        if self.processing:
            return
        
        paths = self.tk.splitlist(event.data)
        added = 0
        excluded = 0
        for p in paths:
            p = p.strip("{}")  # Windowsではパスが{}で囲まれる場合がある
            # ファイルの存在確認
            if not os.path.exists(p):
                continue

            # 除外パターン
            if self._is_excluded_name(p):
                self.log(f"除外パターン一致のためスキップ: {os.path.basename(p)}")
                excluded += 1
                continue

            # フォルダの場合はフォルダ自体を1エントリとして追加（書籍フォルダとして処理）
            if os.path.isdir(p):
                if p not in self.input_files:
                    self.input_files.append(p)
                    self._tree_add_top(p, is_folder=True)
                    added += 1
            else:
                # 単一ファイルの場合
                if p not in self.input_files:
                    self.input_files.append(p)
                    self._tree_add_top(p, is_folder=False)
                    added += 1
                    
        if added > 0:
            self.log(f"{added}件追加しました（フォルダは書籍フォルダとして処理されます）。")
            self.update_file_count()

    # --- 入出力選択 ---
    def select_input_files(self):
        if self.processing:
            return
       
        files = filedialog.askopenfilenames(
            title="入力ファイルを選択",
            filetypes=[
                ("対応画像形式", "*.jpg *.jpeg *.png *.webp *.tiff *.gif *.bmp"),
                ("アーカイブ", "*.zip *.rar"),
                ("すべてのファイル", "*.*")
            ]
        )
        if files:
            added = 0
            excluded = 0
            for f in files:
                if self._is_excluded_name(f):
                    self.log(f"除外パターン一致のためスキップ: {os.path.basename(f)}")
                    excluded += 1
                    continue
                if f not in self.input_files:
                    self.input_files.append(f)
                    self._tree_add_top(f, is_folder=False)
                    added += 1
                    
            if added > 0:
                self.log(f"{added}件のファイルを追加しました。")
                self.update_file_count()

    def select_input_folder(self):
        """[フォルダ選択]ボタンからフォルダを選択し書籍フォルダとして追加"""
        if self.processing:
            return
        folder = filedialog.askdirectory(title="書籍フォルダを選択")
        if folder and folder not in self.input_files:
            if self._is_excluded_name(folder):
                self.log(f"除外パターン一致のためスキップ: {os.path.basename(folder)}")
                return
            self.input_files.append(folder)
            self._tree_add_top(folder, is_folder=True)
            self.log(f"フォルダを追加: {folder}")
            self.update_file_count()

    def select_output_folder(self):
        if self.processing:
            return
           
        folder = filedialog.askdirectory(title="出力先フォルダ")
        if folder:
            self.output_folder.set(folder)
            self.log(f"出力先: {folder}")
           
            # フォルダが存在しない場合は作成
            if not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                    self.log(f"フォルダを作成しました: {folder}")
                except Exception as e:
                    self.log_error(f"フォルダ作成エラー: {e}")

    # --- 実行 ---
    def start_execute(self):
        if self.processing:
            return
        
        # 出力先を決定（テスト出力設定がONの場合はテスト出力先を使用）
        output_dir = self.test_output_folder.get() if self.use_test_output.get() else self.output_folder.get()
        
        # 出力先ログを表示
        if self.use_test_output.get():
            self.log(f"テスト出力モードを使用します: {output_dir}")
           
        # 出力フォルダの作成
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                self.log_error(f"出力フォルダ作成エラー: {e}")
                messagebox.showerror(LANG["error"], f"出力フォルダの作成に失敗しました: {e}")
                return
               
        t = threading.Thread(target=self.execute_process, daemon=True)
        t.start()

    def execute_process(self):
        if not self.input_files:
            self.log_error(LANG["no_input"])
            messagebox.showerror(LANG["error"], LANG["no_input"])
            return
            
        # 出力先を決定（テスト出力設定がONの場合はテスト出力先を使用）
        output_dir = self.test_output_folder.get() if self.use_test_output.get() else self.output_folder.get()
        
        if not output_dir:
            self.log_error(LANG["no_output"])
            messagebox.showerror(LANG["error"], LANG["no_output"])
            return

        # 処理中状態に設定
        self.processing = True
        self.cancel_processing = False
        self.pause_processing = False
        self.execute_button.config(state=tk.DISABLED, text="実行中...", bg="#33AA33")
        self.pause_button.config(text="一時停止", bg="#FFCC66", state=tk.NORMAL)
        self.cancel_button.config(state=tk.NORMAL)
        self.progress_var.set(0)

        # 処理時間計測用の初期化
        self.start_time = time.time()
        self.processed_count = 0
        self.update_time_info()  # 時間表示の更新を開始

        # UIの応答性を保つためのタイマーを設定
        def update_ui():
            if self.processing:
                self.run_on_ui_thread(self.update_idletasks)
                self.run_on_ui_thread(lambda: self.after(100, update_ui))

        # UIの更新タイマーを開始
        update_ui()
        
        # 処理済みファイルのリストをクリア
        self.processed_files = []
        
        # 処理開始時に画像表示をクリア
        self.run_on_ui_thread(self.update_processing_image, None)
       
        try:
            self.log(LANG["start"])
            self.size_summary.clear()
            
            # 重要: ここで処理開始前に変数を初期化
            selected_files = list(self.input_files)  # 処理前に変数を確実に初期化

            # 実書籍数を計算（フォルダ内のアーカイブも展開してカウント）
            self.total_count = self._compute_total_actual_count(self.input_files)
            
            # 一時ファイルリストをクリア
            self.temp_files.clear()
            
            # バッチ処理のためにファイルをグループ化
            batch_size = self.batch_size.get()
            batches = [self.input_files[i:i + batch_size] for i in range(0, len(self.input_files), batch_size)]
            
            total_files = len(self.input_files)
            processed_count = 0
            
            # UIの応答性を保つためのカウンタとインターバル
            update_counter = 0
            ui_update_interval = 5  # 5回に1回UIを更新
            
            # 一時停止フラグをチェックするコールバック関数
            def is_paused():
                return self.pause_processing
            
            # 各バッチを処理
            for batch_index, batch in enumerate(batches):
                # 中止確認
                if self.cancel_processing:
                    self.log("ユーザーによって処理が中止されました")
                    break
                    
                self.log(f"バッチ {batch_index+1}/{len(batches)} 処理中 ({len(batch)}ファイル)")
                
                # マルチスレッドでバッチを処理
                workers = min(self.get_optimal_workers(), os.cpu_count() - 1) if os.cpu_count() > 1 else 1
                self.log(f"並列ワーカー数: {workers}")
                
                # UIを強制更新して応答性を確保
                self.run_on_ui_thread(self.update)
                self.run_on_ui_thread(self.update_idletasks)
                
                # ThreadPoolExecutorを使用
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {}
                    for inpath in batch:
                        # 一時停止チェック - 新しいタスク投入前
                        while self.pause_processing and not self.cancel_processing:
                            time.sleep(0.1)
                            self.run_on_ui_thread(self.update)  # UIを更新して応答性を確保
                        
                        # 中止確認
                        if self.cancel_processing:
                            break
                            
                        # 一時停止状態をチェックするコールバック関数を渡す
                        future = executor.submit(self.process_file, inpath, output_dir, is_paused)
                        futures[future] = inpath
                    
                    for future in concurrent.futures.as_completed(futures):
                        inpath = futures[future]
                        processed_count += 1
                        
                        # 一時停止中は待機（メインスレッドでの処理制御）
                        while self.pause_processing and not self.cancel_processing:
                            time.sleep(0.1)
                            self.run_on_ui_thread(self.update)  # UIを更新して応答性を確保
                        
                        # 中止確認
                        if self.cancel_processing:
                            break
                        
                        # プログレスバー更新
                        self.progress_var.set((processed_count / total_files) * 100)
                        self.progress_label.config(text=LANG["processing"].format(
                            os.path.basename(inpath), processed_count, total_files
                        ))
                        
                        # UIの定期的な更新（すべての更新ではなく間引く）
                        update_counter += 1
                        if update_counter % ui_update_interval == 0:
                            self.run_on_ui_thread(self.update_idletasks)
                        
                        try:
                            future.result()
                            # 成功した場合は処理済みリストに追加
                            if inpath not in self.processed_files:
                                self.processed_files.append(inpath)
                        except Exception as e:
                            self.log_error(f"{LANG['error_msg']} {e}", inpath)
                            logger.exception(f"Error processing {inpath}")
                            self.size_summary[inpath] = (os.path.getsize(inpath), 0, True, f"エラー: {str(e)}")
                
                # バッチ処理後にUIを更新し応答性を確保
                self.run_on_ui_thread(self.update)
                self.run_on_ui_thread(self.update_idletasks)
                
                # メモリ状況を確認し表示
                self.run_on_ui_thread(self.update_memory_usage, force_update=True)
                
                # バッチごとに進捗を保存
                self.save_logs_to_file()
                
                # 中止確認
                if self.cancel_processing:
                    break
            
            # 中止された場合も含めて、未処理のファイルをスキップとしてマーク
            remaining_files = [f for f in self.input_files if f not in self.processed_files]
            if self.cancel_processing and remaining_files:
                self.log(f"ユーザー中止により {len(remaining_files)} 件のファイルが処理されませんでした")
                
                # 未処理のファイルを「中止によりスキップ」としてマーク
                for f in remaining_files:
                    try:
                        size = os.path.getsize(f)
                        self.size_summary[f] = (size, 0, True, "ユーザーによる処理中止")
                    except:
                        self.size_summary[f] = (0, 0, True, "ユーザーによる処理中止")
            
            # 処理完了後にプログレスバーを更新
            self.run_on_ui_thread(self.progress_var.set, 100)
            status_text = LANG["cancelled_progress"] if self.cancel_processing else LANG["completed"]
            self.run_on_ui_thread(self.progress_label.config, text=status_text)
           
            self.log(LANG["end"])
            
            # 処理されたファイル情報の詳細を収集
            processed_files_info = []
            for file_path in selected_files:
                if file_path in self.size_summary:
                    # 安全なアクセス方法に変更
                    summary_data = self.size_summary[file_path]
                    orig_size = summary_data[0] if len(summary_data) > 0 else 0
                    final_size = summary_data[1] if len(summary_data) > 1 else 0
                    skipped = summary_data[2] if len(summary_data) > 2 else False
                    reason = summary_data[3] if len(summary_data) > 3 else ""
                    
                    file_info = {
                        "name": os.path.basename(file_path),
                        "path": file_path,
                        "original_size": orig_size,
                        "final_size": final_size if not skipped else 0,
                        "compression_ratio": (1 - final_size / orig_size) * 100 if orig_size > 0 and not skipped else 0,
                        "skipped": skipped,
                        "reason": reason,
                        "extension": os.path.splitext(file_path)[1].lower()
                    }
                    processed_files_info.append(file_info)
            
            # 処理結果を履歴に追加
            elapsed_time = time.time() - self.start_time
            
            # ファイル形式のカウントを準備
            file_type_counts = {
                ".jpg": 0, ".jpeg": 0, ".png": 0, ".webp": 0, 
                ".tiff": 0, ".gif": 0, ".bmp": 0, ".zip": 0, ".rar": 0, "other": 0
            }
            
            # ファイル形式をカウント
            for file_info in processed_files_info:
                ext = file_info.get("extension", "").lower()
                if ext in file_type_counts:
                    file_type_counts[ext] += 1
                else:
                    file_type_counts["other"] += 1
            
            # 最終的なファイル形式カウントをまとめる
            # JPGとJPEGを統合
            file_type_counts[".jpg"] += file_type_counts[".jpeg"]
            file_type_counts.pop(".jpeg", None)
            
            history_entry = {
                "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": len(selected_files),
                "processed": processed_count,
                "settings": {
                    "jpeg_quality": self.jpeg_quality.get(),
                    "jpeg_progressive": self.jpeg_progressive.get(),
                    "png_compression_level": self.png_compression_level.get(),
                    "resize_mode": self.resize_mode.get(),
                    "resize_width": self.resize_width.get(),
                    "resize_height": self.resize_height.get(),
                    "webp_quality": self.webp_quality.get(),
                    "skip_if_larger": self.skip_if_larger.get(),
                    "use_test_output": self.use_test_output.get(),
                    "output_folder": output_dir
                },
                "size_summary": {
                    "before": sum(data[0] for data in self.size_summary.values() if len(data) > 0),
                    "after": sum(data[1] for data in self.size_summary.values() if len(data) > 1 and not data[2]),
                },
                "file_types": file_type_counts,
                "errors": sum(1 for data in self.size_summary.values() if len(data) > 2 and data[2]),
                "elapsed_time": elapsed_time,
                "detailed_files": processed_files_info,  # 詳細なファイル情報を追加
                "cancelled": self.cancel_processing
            }
            
            # 履歴の先頭に追加
            self.history.insert(0, history_entry)
            
            # 履歴が多すぎる場合は古いものを削除
            if len(self.history) > 100:
                self.history = self.history[:100]
            
            # 履歴を保存
            self.save_history()
            
            # 最終的な進捗とログを保存
            self.save_logs_to_file()
            
            # 処理完了時に音を鳴らす（Windows標準音）
            try:
                winsound.PlaySound("SystemComplete", winsound.SND_ALIAS)
            except Exception as e:
                self.log_error(f"音声再生エラー: {e}")
            
            # 実行後、処理済みファイルリストをクリア（この位置に移動）
            self.input_files.clear()
            self._tree_clear_all()
            self.update_file_count()
           
            # 結果表示（各ファイルのサイズ削減結果）- 中止した場合も表示
            self.show_result_dialog(selected_files, is_cancelled=self.cancel_processing)
            
        except Exception as e:
            # 予期しない例外発生時
            error_message = f"処理中に予期しないエラーが発生しました: {self.translate_error(str(e))}"
            self.log_error(error_message)
            logger.critical(error_message, exc_info=True)
            
            # エラー時に selected_files が定義されていない場合の対処
            if 'selected_files' not in locals():
                selected_files = list(self.input_files)
            
            # 進捗とログを強制的に保存
            self.save_logs_to_file()
            
            # エラーダイアログ表示（日本語化）
            messagebox.showerror(
                LANG["error"], 
                f"処理中にエラーが発生しました。\n\n{self.translate_error(str(e))}\n\n処理済みファイルとエラーログは保存されています。"
            )
        finally:
            # 処理中状態を解除
            self.processing = False
            self.execute_button.config(state=tk.NORMAL, text=LANG["execute"], bg="#66CC66")
            self.pause_button.config(text="一時停止", state=tk.DISABLED, bg="#FFCC66")
            self.cancel_button.config(state=tk.DISABLED)
           
            # 一時ファイルを削除
            self.cleanup_temp_files()
            
            # 処理完了時に画像表示をクリア
            self.run_on_ui_thread(self.update_processing_image, None)
            
            # 現在の書籍ファイルをクリア
            self.current_archive = None

    def process_file_external(self, inpath, output_dir):
        """ProcessPoolExecutor用の外部プロセス処理関数"""
        try:
            ext = os.path.splitext(inpath)[1].lower()
            orig_size = os.path.getsize(inpath)
            
            # 一時ディレクトリの作成
            with tempfile.TemporaryDirectory() as temp_dir:
                if ext in [".zip", ".rar"]:
                    if ext == ".rar" and not self.check_7z():
                        return (orig_size, 0, True, "7-Zip未インストール")
                    
                    # アーカイブの処理は外部プロセスでは複雑なので、
                    # ここではスキップして通常の処理に回す
                    return None
                    
                elif ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
                    tmpfile = os.path.join(temp_dir, os.path.basename(inpath))
                    shutil.copy2(inpath, tmpfile)
                    compressed_dir = os.path.join(temp_dir, "compressed")
                    os.makedirs(compressed_dir, exist_ok=True)
                    
                    # パラメータ準備
                    params = {
                        'jpeg_quality': self.jpeg_quality.get(),
                        'jpeg_progressive': self.jpeg_progressive.get(),
                        'jpeg_keep_metadata': self.jpeg_keep_metadata.get(),
                        'png_compression_level': self.png_compression_level.get(),
                        'png_keep_metadata': self.png_keep_metadata.get(),
                        'webp_quality': self.webp_quality.get(),
                        'webp_keep_metadata': self.webp_keep_metadata.get(),
                        'tiff_keep_metadata': self.tiff_keep_metadata.get(),
                        'resize_mode': self.resize_mode.get(),
                        'resize_width': self.resize_width.get(),
                        'resize_height': self.resize_height.get(),
                        'resize_modes': LANG["resize_modes"],
                        'skip_if_larger': self.skip_if_larger.get(),
                        'file_suffix': self.file_suffix.get(),
                        'base_folder': temp_dir
                    }
                    
                    result = compress_image_worker(tmpfile, compressed_dir, **params)
                    
                    if result[1]:  # 圧縮結果が存在する場合
                        compressed_file = result[1]
                        
                        # 出力先パスの作成
                        base = os.path.splitext(os.path.basename(inpath))[0]
                        out_ext = os.path.splitext(compressed_file)[1]
                        out_name = base + self.file_suffix.get() + out_ext
                        out_path = os.path.join(output_dir, out_name)
                        
                        # 既に同名ファイルがある場合の処理
                        if os.path.exists(out_path):
                            base_name = os.path.splitext(os.path.basename(inpath))[0] + self.file_suffix.get()
                            counter = 1
                            while os.path.exists(os.path.join(output_dir, f"{base_name}_{counter}{out_ext}")):
                                counter += 1
                            out_path = os.path.join(output_dir, f"{base_name}_{counter}{out_ext}")
                        
                        # 圧縮結果を出力先にコピー
                        shutil.copy2(compressed_file, out_path)
                        
                        # 日時をコピー
                        try:
                            shutil.copystat(inpath, out_path)
                        except:
                            pass
                        
                        # 元ファイル削除（オプション）
                        if self.delete_original.get():
                            try:
                                if self.delete_original_mode.get() == "trash":
                                    # ゴミ箱に入れる
                                    send2trash.send2trash(inpath)
                                else:
                                    # 完全に削除
                                    os.remove(inpath)
                            except:
                                pass
                        
                        # 処理結果を返す
                        final_size = os.path.getsize(out_path)
                        return (orig_size, final_size, False, "")
                    else:
                        # エラーメッセージがある場合
                        return (orig_size, 0, True, result[2])
                else:
                    return (orig_size, 0, True, "未対応ファイル形式")
        except Exception as e:
            return (orig_size, 0, True, f"処理エラー: {str(e)}")

    def show_result_dialog(self, processed_files, is_cancelled=False):
        """処理結果を表示するダイアログ"""
        # processed_filesが空の場合の防御コード追加
        if not processed_files:
            self.log_error("表示する処理結果がありません")
            return
            
        summary_lines = []
        total_orig = 0
        total_final = 0
        skipped_count = 0
        cancelled_count = 0
        
        # キャンセルメッセージを追加（キャンセルされた場合）
        if is_cancelled:
            summary_lines.append("<cancelled>!!! 処理は途中でユーザーにより中止されました !!!</cancelled>")
            summary_lines.append("")  # 空行を追加
        
        # 処理したすべてのファイルを表示
        for f in processed_files:
            if f in self.size_summary:
                summary_data = self.size_summary[f]
                
                # 形式の違いに対応（安全なアクセス）
                orig_size = summary_data[0] if len(summary_data) > 0 else 0
                final_size = summary_data[1] if len(summary_data) > 1 else 0
                skipped = summary_data[2] if len(summary_data) > 2 else False
                reason = summary_data[3] if len(summary_data) > 3 else ""
                
                if skipped:
                    skipped_count += 1
                    # 中止による場合は特別なスタイルで表示
                    if "ユーザーによる処理中止" in reason:
                        cancelled_count += 1
                        summary_lines.append(f"<cancelled>{os.path.basename(f)} [未処理: {reason}]</cancelled>")
                    else:
                        summary_lines.append(f"<skipped>{os.path.basename(f)} [スキップ: {reason}]</skipped>")
                else:
                    reduction = (1 - final_size / orig_size) * 100 if orig_size > 0 else 0
                    summary_lines.append(f"{os.path.basename(f)} [{self.format_size(orig_size)} → {self.format_size(final_size)}], <blue>{reduction:.1f}% 削減</blue>")
                    total_orig += orig_size
                    total_final += final_size
            else:
                # size_summaryにない場合（エラー発生など）
                summary_lines.append(f"<skipped>{os.path.basename(f)} [処理なし]</skipped>")
                skipped_count += 1
        
        # 合計情報
        if total_orig > 0:
            reduction = (1 - total_final / total_orig) * 100
            summary_lines.append(f"\n合計: {self.format_size(total_orig)} → {self.format_size(total_final)}, <blue>{reduction:.1f}% 削減</blue>")
        
        if skipped_count - cancelled_count > 0:
            summary_lines.append(f"\nスキップされたファイル: {skipped_count - cancelled_count}件")
        
        if cancelled_count > 0:
            summary_lines.append(f"処理中止によりスキップされたファイル: {cancelled_count}件")
        
        # 結果ダイアログの作成
        result_dialog = tk.Toplevel(self)
        result_dialog.title(LANG["result"])
        result_dialog.geometry("600x400")
        result_dialog.minsize(400, 300)
        
        # スクロール可能なテキストエリア
        result_frame = tk.Frame(result_dialog)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        result_scrollbar = tk.Scrollbar(result_frame)
        result_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        result_text = tk.Text(result_frame, wrap=tk.WORD, padx=10, pady=10)
        result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # スクロールバーとテキストエリアを連動
        result_text.config(yscrollcommand=result_scrollbar.set)
        result_scrollbar.config(command=result_text.yview)
        
        # タグの設定
        result_text.tag_configure("skipped", foreground="red")
        result_text.tag_configure("cancelled", foreground="red", font=("", 0, "bold"))  # 中止分は太字赤
        result_text.tag_configure("blue", foreground="blue")
        
        # タグ付きテキストを挿入
        for line in summary_lines:
            if line.startswith("<cancelled>") and line.endswith("</cancelled>"):
                # タグを削除して太字赤色で表示
                line_text = line[11:-12]
                result_text.insert(tk.END, line_text + "\n", "cancelled")
            elif line.startswith("<skipped>") and line.endswith("</skipped>"):
                # タグを削除して赤色で表示
                line_text = line[9:-10]
                result_text.insert(tk.END, line_text + "\n", "skipped")
            elif "<blue>" in line and "</blue>" in line:
                # 青色タグの適用
                parts = line.split("<blue>")
                before_text = parts[0]
                rest = parts[1].split("</blue>")
                blue_text = rest[0]
                after_text = rest[1] if len(rest) > 1 else ""
                
                result_text.insert(tk.END, before_text)
                result_text.insert(tk.END, blue_text, "blue")
                result_text.insert(tk.END, after_text + "\n")
            else:
                result_text.insert(tk.END, line + "\n")
        
        # 読み取り専用に設定
        result_text.config(state=tk.DISABLED)
        
        # 閉じるボタン
        tk.Button(result_dialog, text="閉じる", command=result_dialog.destroy).pack(pady=10)

    def extract_archive(self, inpath, ext, out_dir):
        """アーカイブを展開し、フォルダ構造をチェック"""
        try:
            if ext == ".zip":
                # あらかじめパスをUNICODEに変換（Windowsパス問題対策）
                inpath = os.path.abspath(inpath)
                out_dir = os.path.abspath(out_dir)
                
                is_multi_folder = False
                
                # ZIPファイルの構造チェック
                with zipfile.ZipFile(inpath, 'r') as z:
                    # ZIP内の構造をチェック
                    folders = set()
                    sub_folders = set()
                    
                    for name in z.namelist():
                        # フォルダ構造を解析
                        parts = name.split('/')
                        if len(parts) > 1:
                            # 最上位フォルダを記録
                            if parts[0]:
                                folders.add(parts[0])
                            
                            # サブフォルダ構造をチェック
                            for i in range(1, len(parts) - 1):
                                if parts[i]:  # 空でない部分のみチェック
                                    parent_path = '/'.join(parts[:i])
                                    if parent_path in folders or parent_path in sub_folders:
                                        sub_folders.add(parent_path + '/' + parts[i])
                    
                    # 最上位フォルダが複数ある場合
                    if len(folders) > 1:
                        is_multi_folder = True
                    
                    # サブフォルダが複数ある場合もチェック
                    if len(folders) == 1:
                        main_folder = next(iter(folders))
                        sub_folder_count = sum(1 for sf in sub_folders if sf.startswith(main_folder))
                        if sub_folder_count > 1:
                            is_multi_folder = True
                
                # ファイルハンドルを確実に解放するため明示的に閉じたあとで処理
                import gc
                gc.collect()
                
                # 複数フォルダ構造でも展開処理を行う（v2: 構造維持型圧縮対応）
                if is_multi_folder:
                    self.log(f"複数フォルダ構造を検出: {inpath} - 構造を維持して処理します")
                
                # ZIPファイルを展開
                with zipfile.ZipFile(inpath, 'r') as z:
                    z.extractall(out_dir)
            
            # RARファイルの処理
            elif ext == ".rar":
                # 7-Zipを使用してRARを展開
                cmd = ["7z", "x", "-y", "-o" + out_dir, inpath]
                result = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode != 0:
                    raise Exception(f"7z error: {result.stderr}")
                
                # 展開後のフォルダ構造を再帰的にチェック
                folders = []
                is_multi_folder = False
                
                for root, dirs, _ in os.walk(out_dir):
                    # ルートディレクトリのすぐ下の階層だけを確認
                    if root == out_dir:
                        if len(dirs) > 1:
                            is_multi_folder = True
                            break
                        folders.extend([os.path.join(root, d) for d in dirs])
                    
                    # サブフォルダがある場合、そのサブフォルダ内のフォルダ構造もチェック
                    elif any(root.startswith(f) for f in folders):
                        parent_folder = next(f for f in folders if root.startswith(f))
                        relative_path = os.path.relpath(root, parent_folder)
                        # 直下の階層に複数のフォルダがあるかチェック
                        if len(relative_path.split(os.sep)) == 1 and len(dirs) > 1:
                            is_multi_folder = True
                            break
                
                # 複数フォルダ構造でもそのまま処理を続行する（v2: 構造維持型圧縮対応）
                if is_multi_folder:
                    self.log(f"複数フォルダ構造を検出（RAR）: {inpath} - 構造を維持して処理します")
            
            self.log(LANG["extract_complete"].format(inpath, out_dir))
            return True
            
        except Exception as e:
            self.log_error(f"解凍エラー: {e}", inpath)
            raise

    def process_file(self, inpath, output_dir, pause_callback=None, container_root=None, output_root=None):
        # 現在処理中のファイル名を表示
        self.run_on_ui_thread(self.update_current_file_display, inpath)
        # ツリービューのステータスを「処理中」に更新
        self.run_on_ui_thread(self.update_tree_status, inpath, "処理中", None)
        
        # 処理開始時に現在の書籍ファイルを設定
        self.current_archive = inpath
        
        # 一時停止チェック関数
        def check_pause():
            if pause_callback and pause_callback():
                while pause_callback() and not self.cancel_processing:
                    time.sleep(0.1)
                    # メインスレッドにUIの更新を依頼
                    self.run_on_ui_thread(self.update)
        
        # 最初の一時停止チェック
        check_pause()
        
        # フォルダの場合: 中身を判定して振り分け
        if os.path.isdir(inpath):
            self._process_folder(inpath, output_dir, pause_callback, check_pause, output_root=(output_root or output_dir))
            return

        # 自動置き換え時は出力先にフォルダ/ファイルを作らずステージングへ書き出す
        if self.auto_replace_enabled.get():
            output_dir = self._get_auto_replace_staging_dir()

        # 画像ファイルの場合は現在処理中の画像を表示
        ext = os.path.splitext(inpath)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
            self.run_on_ui_thread(self.update_processing_image, inpath)
                
        orig_size = os.path.getsize(inpath)
        
        # 一時停止チェック
        check_pause()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            if ext in [".zip", ".rar"]:
                if ext == ".rar" and not self.has_7z:
                    self.log_error("7-Zipがインストールされていないため、RARファイルは処理できません。", inpath)
                    self.log_skip(os.path.basename(inpath), "7-Zip未インストール")
                    self.size_summary[inpath] = (orig_size, 0, True, "7-Zip未インストール")
                    self.run_on_ui_thread(self.update_tree_status, inpath, "スキップ", "")
                    return
                       
                try:
                    # 一時停止チェック
                    check_pause()

                    # 処理済みマーカー検出時はスキップ（ZIPのみ判定可能）
                    if ext == ".zip" and self.skip_already_processed.get() and self.is_already_processed(inpath):
                        self.log(f"[再処理スキップ] 処理済みマーカーを検出: {os.path.basename(inpath)}")
                        self.log_skip(os.path.basename(inpath), "処理済みマーカー検出（再処理スキップ）", inpath)
                        self.size_summary[inpath] = (orig_size, 0, True, "処理済みマーカー検出")
                        self.run_on_ui_thread(self.update_tree_status, inpath, "スキップ", "")
                        return

                    # 解凍処理が成功したかどうかをチェック
                    if not self.extract_archive(inpath, ext, temp_dir):
                        # すでにsize_summaryに記録されているのでreturn
                        return
                    
                    # 一時停止チェック
                    check_pause()
                       
                    compressed_dir = os.path.join(temp_dir, "compressed")
                    os.makedirs(compressed_dir, exist_ok=True)
                    
                    # 書籍ファイル情報を渡す
                    self.compress_images_flat(temp_dir, compressed_dir, archive_file=inpath, pause_callback=pause_callback)
                    
                    # 一時停止チェック
                    check_pause()
                       
                    # 出力ファイル名の作成
                    out_name = os.path.splitext(os.path.basename(inpath))[0] + self.file_suffix.get() + ".zip"
                    out_path = os.path.join(output_dir, out_name)
                       
                    # 既に同名ファイルがある場合の処理
                    if os.path.exists(out_path):
                        base_name = os.path.splitext(os.path.basename(inpath))[0] + self.file_suffix.get()
                        counter = 1
                        while os.path.exists(os.path.join(output_dir, f"{base_name}_{counter}.zip")):
                            counter += 1
                        out_path = os.path.join(output_dir, f"{base_name}_{counter}.zip")
                    
                    # 一時停止チェック
                    check_pause()
                       
                    self.log(LANG["new_zip"].format(out_path))
                    self.create_zip_from_folder(compressed_dir, out_path)

                    # 出力ZIPの破損チェック
                    expected = self._count_files_in_dir(compressed_dir)
                    if not self.verify_output_zip(out_path, expected_count=expected):
                        self.log_error(f"出力ZIPの検証に失敗しました: {out_path}", inpath)

                    # ZIPファイルの日時を元と合わせる
                    try:
                        shutil.copystat(inpath, out_path)
                    except Exception as e:
                        self.log(LANG["copy_date_fail"].format(e))

                    final_size = os.path.getsize(out_path)

                    # 圧縮率5%未満なら破損リスクを避けてスキップ（元ファイルを保持）
                    if self._is_low_reduction_skip(orig_size, final_size, inpath, out_path):
                        return

                    # 処理結果を記録（スキップなし）
                    self.size_summary[inpath] = (orig_size, final_size, False, "")

                    # 一時停止チェック
                    check_pause()

                    # 処理後自動置き換えオプション
                    if self.auto_replace_enabled.get():
                        self._apply_auto_replace(inpath, out_path, container_root=container_root, output_dir=(output_root or output_dir))
                    else:
                        # 元ファイル削除（オプション）
                        if self.delete_original.get():
                            parent_dir = os.path.dirname(os.path.abspath(inpath))
                            parent_stat = self._capture_folder_stat(parent_dir)
                            try:
                                self.log(LANG["original_delete"].format(inpath))
                                if self.delete_original_mode.get() == "trash":
                                    send2trash.send2trash(inpath)
                                    self.log(f"ゴミ箱に移動: {inpath}")
                                else:
                                    os.remove(inpath)
                                    self.log(f"完全に削除: {inpath}")
                            except Exception as e:
                                self.log_error(f"元ファイル削除エラー: {e}", inpath)
                            self._restore_folder_stat(parent_dir, parent_stat)
                       
                except Exception as e:
                    self.log_error(f"アーカイブ処理エラー: {e}", inpath)
                    logger.exception(f"Archive processing error for {inpath}")
                    self.log_skip(os.path.basename(inpath), f"アーカイブエラー: {str(e)}", inpath)
                    self.size_summary[inpath] = (orig_size, 0, True, f"エラー: {str(e)}")
                    self.run_on_ui_thread(self.update_tree_status, inpath, "エラー", "")
                    return

            elif ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
                try:
                    # 一時停止チェック
                    check_pause()
                    
                    tmpfile = os.path.join(temp_dir, os.path.basename(inpath))
                    shutil.copy2(inpath, tmpfile)
                    compressed_dir = os.path.join(temp_dir, "compressed")
                    os.makedirs(compressed_dir, exist_ok=True)
                    
                    # パラメータ準備（compress_image代替）
                    params = {
                        'jpeg_quality': self.jpeg_quality.get(),
                        'jpeg_progressive': self.jpeg_progressive.get(),
                        'jpeg_keep_metadata': self.jpeg_keep_metadata.get(),
                        'png_compression_level': self.png_compression_level.get(),
                        'png_keep_metadata': self.png_keep_metadata.get(),
                        'webp_quality': self.webp_quality.get(),
                        'webp_keep_metadata': self.webp_keep_metadata.get(),
                        'tiff_keep_metadata': self.tiff_keep_metadata.get(),
                        'resize_mode': self.resize_mode.get(),
                        'resize_width': self.resize_width.get(),
                        'resize_height': self.resize_height.get(),
                        'resize_modes': LANG["resize_modes"],
                        'skip_if_larger': self.skip_if_larger.get(),
                        'file_suffix': self.file_suffix.get(),
                        'base_folder': temp_dir,
                        'temp_files': self.temp_files,
                        'pause_callback': pause_callback
                    }
                    
                    # 一時停止チェック
                    check_pause()
                    
                    result = compress_image_worker(tmpfile, compressed_dir, **params)
                    
                    # 一時停止チェック
                    check_pause()
                    
                    if result[1]:  # 圧縮結果が存在する場合
                        compressed_file = result[1]
                        
                        # 圧縮後の画像をプレビュー表示
                        self.run_on_ui_thread(self.update_processing_image, compressed_file)
                        
                        # 出力先パスの作成
                        base = os.path.splitext(os.path.basename(inpath))[0]
                        out_ext = os.path.splitext(compressed_file)[1]
                        out_name = base + self.file_suffix.get() + out_ext
                        out_path = os.path.join(output_dir, out_name)
                        
                        # 既に同名ファイルがある場合の処理
                        if os.path.exists(out_path):
                            base_name = os.path.splitext(os.path.basename(inpath))[0] + self.file_suffix.get()
                            counter = 1
                            while os.path.exists(os.path.join(output_dir, f"{base_name}_{counter}{out_ext}")):
                                counter += 1
                            out_path = os.path.join(output_dir, f"{base_name}_{counter}{out_ext}")
                        
                        # 一時停止チェック
                        check_pause()
                        
                        # 圧縮結果を出力先にコピー
                        shutil.copy2(compressed_file, out_path)
                        
                        # 日時をコピー
                        try:
                            shutil.copystat(inpath, out_path)
                        except:
                            pass
                        
                        # 処理結果を記録
                        final_size = os.path.getsize(out_path)

                        # 圧縮率5%未満ならスキップ（元ファイルを保持）
                        if self._is_low_reduction_skip(orig_size, final_size, inpath, out_path):
                            return

                        self.size_summary[inpath] = (orig_size, final_size, False, "")

                        # 一時停止チェック
                        check_pause()

                        # 処理後自動置き換えオプション
                        if self.auto_replace_enabled.get():
                            self._apply_auto_replace(inpath, out_path, container_root=container_root, output_dir=(output_root or output_dir))
                        else:
                            # 元ファイル削除（オプション）
                            if self.delete_original.get():
                                parent_dir = os.path.dirname(os.path.abspath(inpath))
                                parent_stat = self._capture_folder_stat(parent_dir)
                                try:
                                    self.log(LANG["original_delete"].format(inpath))
                                    if self.delete_original_mode.get() == "trash":
                                        send2trash.send2trash(inpath)
                                        self.log(f"ゴミ箱に移動: {inpath}")
                                    else:
                                        os.remove(inpath)
                                        self.log(f"完全に削除: {inpath}")
                                except Exception as e:
                                    self.log_error(f"元ファイル削除エラー: {e}")
                                self._restore_folder_stat(parent_dir, parent_stat)
                    else:
                        # エラーメッセージがある場合
                        self.log_error(f"圧縮処理に失敗しました: {inpath} - {result[2]}")
                        self.log_skip(os.path.basename(inpath), result[2])
                        self.size_summary[inpath] = (orig_size, 0, True, result[2])
                except Exception as e:
                    self.log_error(f"画像処理エラー: {e}")
                    logger.exception(f"Image processing error for {inpath}")
                    self.log_skip(os.path.basename(inpath), f"処理エラー: {str(e)}")
                    self.size_summary[inpath] = (orig_size, 0, True, f"エラー: {str(e)}")
                    return
            else:
                self.log(LANG["not_image_or_archive"])
                self.log_skip(os.path.basename(inpath), "未対応ファイル形式", inpath)
                self.size_summary[inpath] = (orig_size, 0, True, "未対応ファイル形式")
                self.run_on_ui_thread(self.update_tree_status, inpath, "スキップ", "")
                return

        # 処理済みファイルに追加
        self.processed_files.append(inpath)
        # 処理済みカウントを増加
        self.processed_count += 1
        
        # 現在の書籍ファイルをクリア
        self.current_archive = None
        
        # 進捗を保存
        self.save_logs_to_file()
        
        # 結果ログ出力 + ツリービュー更新
        if inpath in self.size_summary:
            data = self.size_summary[inpath]
            if len(data) > 2 and not data[2]:  # スキップされていない場合
                orig, final = data[0], data[1]
                reduction = (1 - final / orig) * 100 if orig > 0 else 0
                self.log(f"圧縮率: {reduction:.1f}% ({self.format_size(orig)} → {self.format_size(final)})")
                self.run_on_ui_thread(self.update_tree_status, inpath, "完了", f"{reduction:.1f}%")
            else:
                # スキップ/エラーの判定
                reason = data[3] if len(data) > 3 else ""
                status = "エラー" if ("エラー" in reason or "失敗" in reason) else "スキップ"
                self.run_on_ui_thread(self.update_tree_status, inpath, status, "")
        else:
            self.run_on_ui_thread(self.update_tree_status, inpath, "完了", "")

    def compress_images_flat(self, src_folder, dst_folder, archive_file=None, pause_callback=None):
        """フォルダ構造を維持したまま画像を圧縮する（v2: 構造維持型）"""
        tasks = []
        image_files = []
       
        # 画像ファイルのリストを作成
        for root, dirs, files in os.walk(src_folder):
            if os.path.abspath(root).startswith(os.path.abspath(dst_folder)):
                continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"]:
                    src_path = os.path.join(root, f)
                    image_files.append(src_path)
       
        # 最適なワーカー数を計算
        workers = self.get_optimal_workers()
        self.log(f"並列ワーカー数: {workers}")
       
        total_images = len(image_files)
        
        # v2: エラーを集約するための辞書 {エラー種別: [ファイル名リスト]}
        error_summary = {}
        processed = 0
       
        # ThreadPoolExecutorのみを使用
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            
            # パラメータ準備
            params = {
                'jpeg_quality': self.jpeg_quality.get(),
                'jpeg_progressive': self.jpeg_progressive.get(),
                'jpeg_keep_metadata': self.jpeg_keep_metadata.get(),
                'png_compression_level': self.png_compression_level.get(),
                'png_keep_metadata': self.png_keep_metadata.get(),
                'webp_quality': self.webp_quality.get(),
                'webp_keep_metadata': self.webp_keep_metadata.get(),
                'tiff_keep_metadata': self.tiff_keep_metadata.get(),
                'resize_mode': self.resize_mode.get(),
                'resize_width': self.resize_width.get(),
                'resize_height': self.resize_height.get(),
                'resize_modes': LANG["resize_modes"],
                'skip_if_larger': self.skip_if_larger.get(),
                'file_suffix': self.file_suffix.get(),
                'base_folder': None,  # v2: 相対パスは呼び出し元で計算済み
                'temp_files': self.temp_files,
                'pause_callback': pause_callback
            }
            
            for src_path in image_files:
                # 一時停止チェック
                if pause_callback and pause_callback():
                    while pause_callback() and not self.cancel_processing:
                        time.sleep(0.1)
                        self.run_on_ui_thread(self.update)
                        
                # 中止確認
                if self.cancel_processing:
                    break
                
                # v2: フォルダ構造を維持するため、相対パスを計算して出力先を決定
                rel_path = os.path.relpath(src_path, src_folder)
                rel_dir = os.path.dirname(rel_path)
                
                # 出力先フォルダを計算（元のフォルダ構造を維持）
                if rel_dir and rel_dir != ".":
                    target_dst_folder = os.path.join(dst_folder, rel_dir)
                else:
                    target_dst_folder = dst_folder
                
                # 出力先フォルダを作成
                os.makedirs(target_dst_folder, exist_ok=True)
                    
                future = executor.submit(compress_image_worker, src_path, target_dst_folder, **params)
                futures[future] = src_path
            
            for future in concurrent.futures.as_completed(futures):
                src_path = futures[future]
                processed += 1
                
                # 一時停止チェック
                if pause_callback and pause_callback():
                    while pause_callback() and not self.cancel_processing:
                        time.sleep(0.1)
                        self.run_on_ui_thread(self.update)
                        
                # 中止確認
                if self.cancel_processing:
                    break
                    
                self.progress_label.config(text=f"画像処理中: {os.path.basename(src_path)} ({processed}/{total_images})")
                self.run_on_ui_thread(self.update_idletasks)
                
                # 処理中の画像を表示
                self.run_on_ui_thread(self.update_processing_image, src_path)
                
                try:
                    result = future.result()
                    if result[2]:  # エラーがある場合
                        # v2: エラーを集約してカウント（個別ログではなくまとめて表示）
                        error_msg = result[2]
                        if error_msg not in error_summary:
                            error_summary[error_msg] = []
                        error_summary[error_msg].append(os.path.basename(src_path))
                except Exception as e:
                    error_msg = f"エラー発生: {e}"
                    if error_msg not in error_summary:
                        error_summary[error_msg] = []
                    error_summary[error_msg].append(os.path.basename(src_path))
                    logger.exception(f"Error in compress_image for {src_path}")
        
        # v2: 処理完了後にエラーをまとめて表示
        if error_summary:
            archive_name = os.path.basename(archive_file) if archive_file else "不明"
            summary_lines = []
            for error_type, files in error_summary.items():
                count = len(files)
                if "スキップ" in error_type:
                    # スキップは件数のみ表示（正常動作なので詳細不要）
                    summary_lines.append(f"  - {error_type}: {count}件")
                else:
                    # その他のエラーは件数と最初の数ファイルを表示
                    if count <= 3:
                        file_list = ", ".join(files)
                    else:
                        file_list = ", ".join(files[:3]) + f" 他{count-3}件"
                    summary_lines.append(f"  - {error_type}: {count}件 ({file_list})")
            
            summary_text = f"[{archive_name}] 処理サマリー:\n" + "\n".join(summary_lines)
            self.log(summary_text)

    def _process_folder(self, folder_path, output_dir, pause_callback, check_pause, output_root=None):
        """選択フォルダの内容を判定して振り分ける。

        - 書籍アーカイブ(.zip/.cbz/.rar)を含む → コンテナとして各書籍を個別処理（サブフォルダ構造を維持）
        - 画像のみ → フォルダ自体を1つの書籍として処理
        """
        archives = []
        has_loose_images = False
        IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".gif", ".bmp"}
        ARC_EXTS = {".zip", ".cbz", ".rar"}
        for root, dirs, files in os.walk(folder_path):
            # 除外パターンに一致するサブフォルダは降りない
            dirs[:] = [d for d in dirs if not any(pat and pat in d for pat in self.excluded_name_patterns)]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                full = os.path.join(root, f)
                if self._is_excluded_path(full, base=folder_path):
                    continue
                if ext in ARC_EXTS:
                    archives.append(full)
                elif ext in IMG_EXTS:
                    has_loose_images = True

        effective_root = output_root or output_dir
        if archives:
            if has_loose_images:
                self.log("[警告] フォルダ内にアーカイブと裸の画像が混在しています。アーカイブのみ処理します。")
            self._process_folder_as_container(folder_path, archives, output_dir, pause_callback, check_pause, output_root=effective_root)
        else:
            self._process_folder_as_archive(folder_path, output_dir, pause_callback, check_pause)

    def _process_folder_as_container(self, folder_path, archives, output_dir, pause_callback, check_pause, output_root=None):
        """フォルダ内の各書籍ファイルを個別に処理し、サブフォルダ構造を維持して出力する。"""
        folder_path_abs = os.path.abspath(folder_path)
        folder_name = os.path.basename(folder_path.rstrip("/\\"))
        self.log(f"[フォルダコンテナ] {len(archives)}件の書籍を処理: {folder_name}")

        agg_orig = 0
        agg_final = 0
        had_success = False

        for archive_path in archives:
            if self.cancel_processing:
                self.log("キャンセルされたため、フォルダ処理を中断しました。")
                break
            check_pause()

            # 相対サブフォルダを計算 (folder_name を含めて出力先に元フォルダを再現)
            rel_dir = os.path.dirname(os.path.relpath(archive_path, folder_path_abs))
            # 自動置き換え時は出力先（ユーザー指定）に痕跡を残さないようテンポラリへ
            if self.auto_replace_enabled.get():
                base_dir = self._get_auto_replace_staging_dir()
            else:
                base_dir = output_dir
            target_output_dir = os.path.join(base_dir, folder_name, rel_dir) if rel_dir else os.path.join(base_dir, folder_name)
            try:
                os.makedirs(target_output_dir, exist_ok=True)
            except Exception as e:
                self.log_error(f"出力サブフォルダ作成失敗: {e}", archive_path)
                continue

            try:
                self.process_file(archive_path, target_output_dir, pause_callback,
                                  container_root=folder_path_abs,
                                  output_root=(output_root or output_dir))
                # 集約サイズ用にsize_summaryから取得
                if archive_path in self.size_summary:
                    data = self.size_summary[archive_path]
                    if len(data) >= 3 and not data[2]:
                        agg_orig += data[0]
                        agg_final += data[1]
                        had_success = True
            except Exception as e:
                self.log_error(f"書籍処理エラー: {e}", archive_path)
                logger.exception(f"Container archive processing error for {archive_path}")

        # 出力先に残った空のサブツリーを掃除（auto_replace後の名残対策）
        effective_root = output_root or output_dir
        try:
            container_top = os.path.join(effective_root, folder_name)
            if os.path.isdir(container_top):
                # 空フォルダを内側から削除
                for root, dirs, files in os.walk(container_top, topdown=False):
                    if not dirs and not files:
                        try:
                            os.rmdir(root)
                        except OSError:
                            pass
        except Exception:
            pass

        # フォルダ自体をsize_summaryに集約として記録（結果ダイアログでスキップ扱いされないように）
        if had_success:
            self.size_summary[folder_path] = (agg_orig, agg_final, False, f"フォルダ: {len(archives)}冊集約")
        else:
            self.size_summary[folder_path] = (0, 0, True, "コンテナ内で成功した書籍がありません")
        # コンテナ完了をprocessed_filesにも追加（show_result_dialogで参照される）
        if folder_path not in self.processed_files:
            self.processed_files.append(folder_path)

    def verify_output_zip(self, out_path, expected_count=None):
        """出力ZIPの破損チェック。問題があればログに警告を出す。

        Returns: True (正常) / False (破損または問題あり)
        """
        try:
            if not os.path.isfile(out_path):
                self.log_error(f"検証: 出力ファイルが存在しません: {out_path}")
                return False

            size = os.path.getsize(out_path)
            # 22バイトは空ZIPのEnd-of-Central-Directoryのみのサイズ
            if size <= 22:
                self.log_error(f"検証: 出力ZIPが空または異常に小さい ({size}バイト): {out_path}")
                return False

            with zipfile.ZipFile(out_path, 'r') as zf:
                bad = zf.testzip()
                if bad is not None:
                    self.log_error(f"検証: ZIP内に破損エントリ '{bad}': {out_path}")
                    return False
                actual_count = len([n for n in zf.namelist() if not n.endswith('/')])

            if actual_count == 0:
                self.log_error(f"検証: 出力ZIPにファイルが含まれていません: {out_path}")
                return False

            if expected_count is not None and actual_count < expected_count:
                self.log_error(
                    f"検証: ファイル数不足 (期待:{expected_count}, 実際:{actual_count}): {out_path}"
                )
                return False

            self.log(f"[検証OK] {os.path.basename(out_path)} ({actual_count}ファイル)")
            return True
        except zipfile.BadZipFile:
            self.log_error(f"検証: 不正なZIPファイル: {out_path}")
            return False
        except Exception as e:
            self.log_error(f"検証エラー: {e}: {out_path}")
            return False

    def _count_files_in_dir(self, dir_path):
        """ディレクトリ内のファイル総数（再帰）"""
        try:
            return sum(len(files) for _, _, files in os.walk(dir_path))
        except Exception:
            return None

    def _compute_total_actual_count(self, input_files):
        """入力リストから実際に処理される書籍数を概算する。

        - ファイル: 1件
        - フォルダ: 内部の .zip/.cbz/.rar の数（あれば）。なければ1件（単一書籍として扱われる）。
        """
        ARC_EXTS = {".zip", ".cbz", ".rar"}
        total = 0
        for p in input_files:
            try:
                if os.path.isdir(p):
                    count = 0
                    for root, _, files in os.walk(p):
                        for f in files:
                            if os.path.splitext(f)[1].lower() in ARC_EXTS:
                                count += 1
                    total += count if count > 0 else 1
                else:
                    total += 1
            except Exception:
                total += 1
        return total

    def _process_folder_as_archive(self, folder_path, output_dir, pause_callback, check_pause):
        """フォルダを1つの書籍として処理し、ZIPに圧縮して出力する。フォルダ構造を維持。"""
        self.current_archive = folder_path
        folder_name = os.path.basename(folder_path.rstrip("/\\"))
        self.log(f"[フォルダ書籍] 処理開始: {folder_name}")
        self.run_on_ui_thread(self.update_tree_status, folder_path, "処理中", None)
        
        try:
            # フォルダの総サイズを計算
            orig_size = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, files in os.walk(folder_path)
                for f in files
            )
            
            with tempfile.TemporaryDirectory() as temp_dir:
                check_pause()
                
                # フォルダ内の画像を圧縮
                compressed_dir = os.path.join(temp_dir, "compressed")
                os.makedirs(compressed_dir, exist_ok=True)
                
                # base_folder を folder_path にして相対パスを維持して圧縮
                self.compress_images_flat(folder_path, compressed_dir, archive_file=folder_path, pause_callback=pause_callback)
                
                check_pause()
                
                # 出力先にフォルダ構造を維持するためのサブフォルダを計算
                # output_dir 直下に folder_name.zip を作成
                out_name = folder_name + self.file_suffix.get() + ".zip"
                out_path = os.path.join(output_dir, out_name)
                
                # 重複時はカウンタを付加
                if os.path.exists(out_path):
                    base_name = folder_name + self.file_suffix.get()
                    counter = 1
                    while os.path.exists(os.path.join(output_dir, f"{base_name}_{counter}.zip")):
                        counter += 1
                    out_path = os.path.join(output_dir, f"{base_name}_{counter}.zip")
                
                check_pause()
                
                self.log(LANG["new_zip"].format(out_path))
                self.create_zip_from_folder(compressed_dir, out_path)

                # 出力ZIPの破損チェック
                expected = self._count_files_in_dir(compressed_dir)
                if not self.verify_output_zip(out_path, expected_count=expected):
                    self.log_error(f"出力ZIPの検証に失敗しました: {out_path}", folder_path)

                # 日時を元フォルダに合わせる
                try:
                    shutil.copystat(folder_path, out_path)
                except Exception as e:
                    self.log(LANG["copy_date_fail"].format(e))

                final_size = os.path.getsize(out_path)

                # 圧縮率5%未満ならスキップ（元フォルダを保持）
                if self._is_low_reduction_skip(orig_size, final_size, folder_path, out_path):
                    return

                self.size_summary[folder_path] = (orig_size, final_size, False, "")

                check_pause()

                # 処理後自動置き換えオプション
                if self.auto_replace_enabled.get():
                    # out_path（ZIP）を元フォルダの親ディレクトリへ移動
                    parent_dir = os.path.dirname(folder_path)
                    dest_zip = os.path.join(parent_dir, os.path.basename(out_path))
                    try:
                        # 既存ファイルがあれば上書き
                        if os.path.exists(dest_zip):
                            os.remove(dest_zip)
                        shutil.move(out_path, dest_zip)
                        self.log(f"元の場所に配置: {dest_zip}")
                        
                        # 元フォルダをバックアップフォルダへ移動
                        backup_folder = self.original_backup_folder.get()
                        if backup_folder and os.path.isdir(backup_folder):
                            dest_folder = os.path.join(backup_folder, folder_name)
                            # 同名フォルダが既にあれば連番を付ける
                            if os.path.exists(dest_folder):
                                counter = 1
                                while os.path.exists(f"{dest_folder}_{counter}"):
                                    counter += 1
                                dest_folder = f"{dest_folder}_{counter}"
                            shutil.move(folder_path, dest_folder)
                            self.log(f"元フォルダを移動: {folder_path} → {dest_folder}")
                        else:
                            self.log_error("元ファイル移動先フォルダが未設定または存在しません", folder_path)
                    except Exception as e:
                        self.log_error(f"自動置き換えエラー: {e}", folder_path)
                else:
                    # 元ファイル削除（オプション）
                    if self.delete_original.get():
                        grandparent_dir = os.path.dirname(os.path.abspath(folder_path))
                        grandparent_stat = self._capture_folder_stat(grandparent_dir)
                        try:
                            self.log(LANG["original_delete"].format(folder_path))
                            if self.delete_original_mode.get() == "trash":
                                send2trash.send2trash(folder_path)
                                self.log(f"ゴミ箱に移動: {folder_path}")
                            else:
                                shutil.rmtree(folder_path)
                                self.log(f"完全に削除: {folder_path}")
                        except Exception as e:
                            self.log_error(f"元フォルダ削除エラー: {e}", folder_path)
                        self._restore_folder_stat(grandparent_dir, grandparent_stat)
                            
        except Exception as e:
            self.log_error(f"フォルダ処理エラー: {e}", folder_path)
            logger.exception(f"Folder processing error for {folder_path}")
            self.log_skip(folder_name, f"フォルダエラー: {str(e)}", folder_path)
            self.size_summary[folder_path] = (0, 0, True, f"エラー: {str(e)}")
            self.run_on_ui_thread(self.update_tree_status, folder_path, "エラー", "")
            return

        # 処理済みリストに追加
        self.processed_files.append(folder_path)
        self.processed_count += 1
        self.current_archive = None
        self.save_logs_to_file()
        # ツリービュー更新
        if folder_path in self.size_summary:
            data = self.size_summary[folder_path]
            if len(data) > 2 and not data[2] and data[0] > 0:
                ratio = (1 - data[1] / data[0]) * 100
                self.run_on_ui_thread(self.update_tree_status, folder_path, "完了", f"{ratio:.1f}%")
            else:
                self.run_on_ui_thread(self.update_tree_status, folder_path, "完了", "")
        
        if folder_path in self.size_summary:
            data = self.size_summary[folder_path]
            if len(data) > 2 and not data[2]:
                orig, final = data[0], data[1]
                reduction = (1 - final / orig) * 100 if orig > 0 else 0
                self.log(f"[フォルダ] 圧縮率: {reduction:.1f}% ({self.format_size(orig)} → {self.format_size(final)})")

    def _capture_folder_stat(self, folder_path):
        """フォルダの atime/mtime を取得（ファイル追加/削除でOSが更新するため）。"""
        try:
            if os.path.isdir(folder_path):
                return os.stat(folder_path)
        except Exception:
            pass
        return None

    def _restore_folder_stat(self, folder_path, stat_obj):
        """フォルダの atime/mtime を復元する。書籍管理アプリの並び順を守る目的。"""
        if stat_obj is None:
            return
        try:
            os.utime(folder_path, (stat_obj.st_atime, stat_obj.st_mtime))
        except Exception as e:
            self.log_error(f"フォルダ日時の復元に失敗: {folder_path} ({e})")

    def _is_low_reduction_skip(self, orig_size, final_size, target_path, out_path):
        """圧縮率が5%未満なら出力を破棄してスキップ扱いにする。Trueを返した場合、呼び出し元は処理を中断する。"""
        if orig_size <= 0:
            return False
        reduction = (1 - final_size / orig_size) * 100
        if reduction >= 5.0:
            return False
        self.log(f"圧縮率{reduction:.1f}%（5%未満）のためスキップ: {target_path}")
        try:
            if out_path and os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        self.size_summary[target_path] = (orig_size, orig_size, True, f"圧縮率不足({reduction:.1f}%)")
        try:
            self.log_skip(os.path.basename(target_path), f"圧縮率{reduction:.1f}%（5%未満）", target_path)
        except TypeError:
            self.log_skip(os.path.basename(target_path), f"圧縮率{reduction:.1f}%（5%未満）")
        self.run_on_ui_thread(self.update_tree_status, target_path, "スキップ(低圧縮率)", f"{reduction:.1f}%")
        return True

    def _get_auto_replace_staging_dir(self):
        """自動置き換え時の出力ステージングディレクトリ（temp_dir 配下）。"""
        staging = os.path.join(self.temp_dir, "_auto_replace_staging")
        try:
            os.makedirs(staging, exist_ok=True)
        except Exception:
            pass
        return staging

    def _cleanup_empty_dirs(self, start_dir, boundary):
        """start_dir から boundary（含まない）まで遡り、空ディレクトリを削除する。"""
        if not start_dir or not boundary:
            return
        try:
            boundary_abs = os.path.abspath(boundary).rstrip("/\\")
            cur = os.path.abspath(start_dir).rstrip("/\\")
            # boundary 配下でないなら何もしない
            if not cur.startswith(boundary_abs + os.sep) and cur != boundary_abs:
                return
            while cur and cur != boundary_abs:
                try:
                    os.rmdir(cur)
                except OSError:
                    break  # 空でない or 削除不可
                cur = os.path.dirname(cur)
        except Exception:
            pass

    def _move_with_retry(self, src, dst, retries=4, delay=1.0):
        """shutil.move をリトライ付きで実行（ファイルロック等の一時的失敗を回避）。

        shutil.move はクロスデバイス時に copy→unlink にフォールバックするが、
        unlink が PermissionError(Errno 13) で失敗するとコピー済みなのに例外が
        伝播しソース側が残るケースがある。その場合は explicit に unlink を
        リトライしてからエラー扱いにする。
        """
        last_exc = None
        for attempt in range(retries):
            try:
                shutil.move(src, dst)
                return True
            except (OSError, PermissionError) as e:
                last_exc = e
                # コピー済み + ソース残存 = 部分移動。ソースを別途削除して回復
                if os.path.exists(dst) and os.path.exists(src):
                    for u_attempt in range(retries):
                        try:
                            os.remove(src)
                            self.log(f"部分移動を回復（コピー成功・ソース手動削除）: {src}")
                            return True
                        except (OSError, PermissionError) as ue:
                            last_exc = ue
                            time.sleep(delay * (u_attempt + 1))
                    # ソース削除も全失敗 → 諦めて例外
                    break
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
        if last_exc:
            raise last_exc
        return False

    def _apply_auto_replace(self, inpath, out_path, container_root=None, output_dir=None):
        """処理後自動置き換え: 元ファイルをバックアップへ移動した後、out_pathを元の場所に配置する。

        container_root が指定されている場合、バックアップ先に
        <container_root の名前>/<相対パス>/<元ファイル名> の構造を再現する。
        output_dir が指定されている場合、処理成功後に out_path の親階層に残った
        空フォルダを output_dir まで遡って削除する。
        """
        try:
            backup_folder = self.original_backup_folder.get()
            if not backup_folder or not os.path.isdir(backup_folder):
                self.log_error(
                    "元ファイル移動先フォルダが未設定または存在しません。自動置き換えを中断しました。",
                    inpath,
                )
                return

            original_dir = os.path.dirname(os.path.abspath(inpath))
            dest_file = os.path.join(original_dir, os.path.basename(out_path))
            out_path_dir = os.path.dirname(os.path.abspath(out_path))

            # 親フォルダの日時を保存（後で復元してComicShare等の並び順を維持）
            parent_stat = self._capture_folder_stat(original_dir)

            # バックアップ先パスの計算（コンテナルートがあれば構造維持）
            if container_root:
                container_name = os.path.basename(os.path.abspath(container_root).rstrip("/\\"))
                rel_path = os.path.relpath(os.path.abspath(inpath), os.path.abspath(container_root))
                backup_target_dir = os.path.join(backup_folder, container_name, os.path.dirname(rel_path))
                os.makedirs(backup_target_dir, exist_ok=True)
                dest_backup = os.path.join(backup_target_dir, os.path.basename(inpath))
            else:
                dest_backup = os.path.join(backup_folder, os.path.basename(inpath))

            # 元ファイル移動先がinpathと同じパスになる場合は中止
            # （元ファイル移動先がソースの親階層にあるなどの誤設定）
            if os.path.abspath(dest_backup) == os.path.abspath(inpath):
                self.log_error(
                    "元ファイル移動先が元ファイルと同じパスに解決されます。"
                    "バックアップ先設定を見直してください。自動置き換えを中断しました。",
                    inpath,
                )
                # 出力先に残ったout_pathも掃除しないと孤立するので削除
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except Exception:
                    pass
                if output_dir:
                    self._cleanup_empty_dirs(out_path_dir, output_dir)
                return

            # 出力ファイルがバックアップ先と同じ場所にある場合は先に退避
            # （出力フォルダ == 元ファイル移動先 のときに発生し、誤って _1 が付くのを防ぐ）
            if os.path.abspath(out_path) == os.path.abspath(dest_backup):
                tmp_out = out_path + ".__mc_swap__"
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
                shutil.move(out_path, tmp_out)
                out_path = tmp_out

            # ステップ1: 元ファイルをバックアップフォルダへ移動（先に実行・リトライ付き）
            if os.path.exists(dest_backup):
                base, ext = os.path.splitext(os.path.basename(inpath))
                target_dir = os.path.dirname(dest_backup)
                counter = 1
                while os.path.exists(os.path.join(target_dir, f"{base}_{counter}{ext}")):
                    counter += 1
                dest_backup = os.path.join(target_dir, f"{base}_{counter}{ext}")
            try:
                self._move_with_retry(inpath, dest_backup)
            except Exception as e:
                raise type(e)(f"[ステップ1: 元ファイル→バックアップ] {inpath} → {dest_backup}: {e}") from e
            self.log(f"元ファイルを移動: {inpath} → {dest_backup}")

            # ステップ2: 出力ファイルを元の場所に配置（リトライ付き）
            if os.path.abspath(out_path) != os.path.abspath(dest_file):
                if os.path.exists(dest_file):
                    os.remove(dest_file)
                try:
                    self._move_with_retry(out_path, dest_file)
                except Exception as e:
                    raise type(e)(f"[ステップ2: 出力→元の場所] {out_path} → {dest_file}: {e}") from e
            self.log(f"元の場所に配置: {dest_file}")

            # 親フォルダの日時を復元（書籍管理アプリの更新日時順を維持）
            self._restore_folder_stat(original_dir, parent_stat)

            # 出力先に残った空フォルダを削除（output_dir 配下のみ・boundary含まず）
            if output_dir:
                self._cleanup_empty_dirs(out_path_dir, output_dir)
        except Exception as e:
            self.log_error(f"自動置き換えエラー: {e}", inpath)
            # 失敗時、out_pathが出力先サブフォルダに孤立しないよう削除
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
                    self.log(f"自動置き換え失敗のため出力ファイルを削除: {out_path}")
            except Exception:
                pass
            if output_dir:
                self._cleanup_empty_dirs(out_path_dir, output_dir)

    def select_backup_folder(self):
        """元ファイルの移動先フォルダを選択"""
        folder = filedialog.askdirectory(title="元ファイルの移動先フォルダを選択")
        if folder:
            self.original_backup_folder.set(folder)

    # ZIPアーカイブのコメントに埋め込む処理済みマーカー（ファイル名は変更せずメタデータで識別）
    PROCESSED_MARKER_PREFIX = "MangaCompressor:processed"

    def is_already_processed(self, zip_path):
        """ZIPコメントを読み、処理済みマーカーが含まれていればTrueを返す。

        対象がZIPでない/開けない場合はFalse（処理対象とする）。
        """
        try:
            if not zipfile.is_zipfile(zip_path):
                return False
            with zipfile.ZipFile(zip_path, 'r') as zf:
                comment = zf.comment or b""
            try:
                text = comment.decode('utf-8', errors='replace')
            except Exception:
                return False
            return self.PROCESSED_MARKER_PREFIX in text
        except Exception:
            return False

    def create_zip_from_folder(self, folder_path, out_zip):
        try:
            with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(folder_path):
                    for f in files:
                        full_path = os.path.join(root, f)
                        arcname = os.path.relpath(full_path, folder_path)
                        zf.write(full_path, arcname)
                # 処理済みマーカーをZIPコメントに埋め込む（ファイル名は変更しない）
                marker = f"{self.PROCESSED_MARKER_PREFIX} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                zf.comment = marker.encode('utf-8')
            self.log(LANG["zip_complete"].format(out_zip))
        except Exception as e:
            self.log_error(f"ZIP作成エラー: {e}")
            raise

    def cleanup_temp_files(self):
        """一時ファイルの削除"""
        for f in self.temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception as e:
                self.log_error(f"一時ファイル削除エラー: {f} - {e}")
        self.temp_files.clear()
    
    def cleanup_temp_dir(self):
        """アプリケーション終了時に一時ディレクトリを削除"""
        try:
            temp_paths = getattr(self, "_managed_temp_dirs", set())
            for temp_path in list(temp_paths):
                if os.path.exists(temp_path):
                    shutil.rmtree(temp_path)
                temp_paths.discard(temp_path)
        except Exception:
            pass

    def format_size(self, size_bytes):
        """バイト数を読みやすいサイズ表記に変換"""
        if size_bytes >= 1024**3:
            return f"{size_bytes/(1024**3):.2f} GB"
        elif size_bytes >= 1024**2:
            return f"{size_bytes/(1024**2):.1f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes/1024:.1f} KB"
        else:
            return f"{size_bytes} B"

    def run_on_ui_thread(self, func, *args, **kwargs):
        """Tk メインスレッドで安全に処理を実行する"""
        if threading.current_thread() == threading.main_thread():
            func(*args, **kwargs)
        else:
            self.ui_queue.put((func, args, kwargs))

    def _process_ui_queue(self):
        """UIスレッドでキューを順に処理する"""
        try:
            while True:
                func, args, kwargs = self.ui_queue.get_nowait()
                try:
                    func(*args, **kwargs)
                except Exception:
                    logger.exception('UI queue dispatch error', exc_info=True)
        except queue.Empty:
            pass
        finally:
            self.after(50, self._process_ui_queue)

    def log(self, message):
        """ログ出力（UIスレッドセーフ）"""
        self.run_on_ui_thread(self._log_internal, message)

    # 処理中ファイル名表示の更新メソッド
    def update_current_file_display(self, filepath):
        """現在処理中のファイル名を表示"""
        if filepath:
            filename = os.path.basename(filepath)
            self.current_file_label.config(text=f"処理中: {filename}", fg="#0000CC")
        else:
            self.current_file_label.config(text="")
      
    # エラー表示を日本語化
    def log_error(self, message, archive_file=None):
        """エラーログ出力（日本語化してファイル名を含む）"""
        # エラーメッセージを日本語化
        translated_message = self.translate_error(message)
        
        archive_info = f"[書籍ファイル: {os.path.basename(archive_file)}] " if archive_file else ""
        full_message = f"エラー: {archive_info}{translated_message}"
        
        # v2: エラーをCSV用構造化データとして保存
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        archive_name = os.path.basename(archive_file) if archive_file else ""
        self.error_log_data.append({
            'timestamp': timestamp,
            'archive': archive_name,
            'type': 'エラー',
            'message': translated_message
        })
        
        # UIに出力
        self.run_on_ui_thread(self._log_internal, full_message, error=True)
        self.run_on_ui_thread(self._log_error_internal, archive_info + translated_message)
        logger.error(full_message)

    def log_skip(self, filename, reason, archive_file=None):
        """スキップ情報をエラーログに出力（書籍ファイル名を含む）"""
        archive_info = f"[書籍ファイル: {os.path.basename(archive_file)}] " if archive_file else ""
        message = f"スキップ: {archive_info}{filename} - {reason}"
        
        # v2: スキップをCSV用構造化データとして保存
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        archive_name = os.path.basename(archive_file) if archive_file else ""
        self.error_log_data.append({
            'timestamp': timestamp,
            'archive': archive_name,
            'type': 'スキップ',
            'filename': filename,
            'message': reason
        })
        
        # UIに出力
        self.run_on_ui_thread(self._log_error_internal, message, is_skip=True)
        logger.info(message)

    def export_error_log_csv(self):
        """v2: エラーログをCSVファイルに出力"""
        if not self.error_log_data:
            messagebox.showinfo("情報", "エラーログデータがありません。")
            return
        
        # 保存先を選択
        current_date = time.strftime("%Y%m%d_%H%M%S")
        default_filename = f"error_log_{current_date}.csv"
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
            initialfile=default_filename,
            title="エラーログをCSVに保存"
        )
        
        if not filepath:
            return
        
        try:
            import csv
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # ヘッダー
                writer.writerow(['タイムスタンプ', 'アーカイブ名', '種別', 'ファイル名', 'メッセージ'])
                
                # データ
                for entry in self.error_log_data:
                    writer.writerow([
                        entry.get('timestamp', ''),
                        entry.get('archive', ''),
                        entry.get('type', ''),
                        entry.get('filename', ''),
                        entry.get('message', '')
                    ])
            
            self.log(f"エラーログをCSV出力しました: {filepath}")
            messagebox.showinfo("完了", f"エラーログを保存しました:\n{filepath}")
            
        except Exception as e:
            self.log_error(f"CSV出力エラー: {e}")
            messagebox.showerror("エラー", f"CSV出力に失敗しました:\n{e}")

    def _log_internal(self, message, error=False):
        """内部ログ処理"""
        current_time = time.strftime("%H:%M:%S")
        if error:
            self.log_text.insert(tk.END, f"[{current_time}] {message}\n", "error")
            self.log_text.tag_configure("error", foreground="red")
        else:
            self.log_text.insert(tk.END, f"[{current_time}] {message}\n")
        self.log_text.see(tk.END)

    def _log_error_internal(self, message, is_skip=False):
        """エラーログ専用のテキストエリアにエラーやスキップ情報を出力"""
        current_time = time.strftime("%H:%M:%S")
        if is_skip:
            # スキップは青色で表示
            self.error_log_text.insert(tk.END, f"[{current_time}] ", "timestamp")
            self.error_log_text.insert(tk.END, message, "skip")
            self.error_log_text.insert(tk.END, "\n")
        else:
            # エラーは赤色で表示
            self.error_log_text.insert(tk.END, f"[{current_time}] ", "timestamp")
            self.error_log_text.insert(tk.END, message, "error")
            self.error_log_text.insert(tk.END, "\n")
        self.error_log_text.see(tk.END)

    def check_7z(self):
        """7zコマンドが使用可能かチェック"""
        try:
            subprocess.run(["7z", "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except (FileNotFoundError, subprocess.SubprocessError):
            return False
           
    def check_caesium_clt(self):
        """Caesium CLTコマンドが使用可能かチェック"""
        try:
            subprocess.run(["caesiumclt", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except (FileNotFoundError, subprocess.SubprocessError):
            return False

    def show_preset_manager(self):
        """プリセット管理ダイアログを表示"""
        preset_window = tk.Toplevel(self)
        preset_window.title("プリセット管理")
        preset_window.geometry("500x400")
        preset_window.minsize(400, 300)
        preset_window.transient(self)  # メインウィンドウに対する子ウィンドウとして設定
        preset_window.grab_set()  # モーダルダイアログとして設定
        
        # メインフレーム
        main_frame = tk.Frame(preset_window, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # タイトル
        tk.Label(main_frame, text="プリセット管理", font=("", 14, "bold")).pack(pady=(0, 10))
        
        # プリセットリストフレーム
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # スクロールバー
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # プリセットリストボックス
        preset_list = tk.Listbox(list_frame, selectmode=tk.SINGLE)
        preset_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        preset_list.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=preset_list.yview)
        
        # 操作ボタンフレーム
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 現在の設定を保存ボタン
        save_button = tk.Button(
            button_frame, 
            text="現在の設定を保存", 
            command=lambda: self.save_preset_from_manager(preset_list)
        )
        save_button.pack(side=tk.LEFT, padx=5)
        
        # 読み込みボタン
        load_button = tk.Button(
            button_frame, 
            text="選択したプリセットを適用", 
            command=lambda: self.load_preset_from_manager(preset_list)
        )
        load_button.pack(side=tk.LEFT, padx=5)
        
        # 削除ボタン
        delete_button = tk.Button(
            button_frame, 
            text="選択したプリセットを削除", 
            command=lambda: self.delete_preset(preset_list)
        )
        delete_button.pack(side=tk.LEFT, padx=5)
        
        # リネームボタン
        rename_button = tk.Button(
            button_frame, 
            text="名前変更", 
            command=lambda: self.rename_preset(preset_list)
        )
        rename_button.pack(side=tk.LEFT, padx=5)
        
        # 閉じるボタン
        close_button = tk.Button(main_frame, text="閉じる", command=preset_window.destroy)
        close_button.pack(pady=10)
        
        # プリセット一覧を更新
        self.populate_preset_list(preset_list)
        
        # ウィンドウの中央配置
        preset_window.update_idletasks()
        width = preset_window.winfo_width()
        height = preset_window.winfo_height()
        x = (preset_window.winfo_screenwidth() // 2) - (width // 2)
        y = (preset_window.winfo_screenheight() // 2) - (height // 2)
        preset_window.geometry(f"{width}x{height}+{x}+{y}")

    def populate_preset_list(self, listbox):
        """プリセットリストにデータを表示"""
        listbox.delete(0, tk.END)
        
        # プリセットディレクトリのチェック
        if not os.path.exists(self.preset_dir):
            os.makedirs(self.preset_dir, exist_ok=True)
        
        # プリセットファイルを検索
        preset_files = [f for f in os.listdir(self.preset_dir) if f.endswith('.json')]
        
        if preset_files:
            for preset_file in sorted(preset_files):
                preset_name = os.path.splitext(preset_file)[0]
                listbox.insert(tk.END, preset_name)
        else:
            listbox.insert(tk.END, "保存されたプリセットはありません")
            listbox.config(state=tk.DISABLED)

    def save_preset_from_manager(self, listbox):
        """プリセット管理画面からプリセットを保存"""
        preset_name = simpledialog.askstring("プリセット保存", "プリセット名を入力してください:")
        if not preset_name:
            return
        
        # ファイル名に使用できない文字を置換
        preset_name = preset_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
        
        # プリセットデータの作成
        preset = {
            "jpeg_quality": self.jpeg_quality.get(),
            "jpeg_progressive": self.jpeg_progressive.get(),
            "jpeg_keep_metadata": self.jpeg_keep_metadata.get(),
            "png_compression_level": self.png_compression_level.get(),
            "png_keep_metadata": self.png_keep_metadata.get(),
            "webp_quality": self.webp_quality.get(),
            "webp_keep_metadata": self.webp_keep_metadata.get(),
            "tiff_keep_metadata": self.tiff_keep_metadata.get(),
            "resize_mode": self.resize_mode.get(),
            "resize_width": self.resize_width.get(),
            "resize_height": self.resize_height.get(),
            "skip_if_larger": self.skip_if_larger.get(),
            "delete_original": self.delete_original.get(),
            "delete_original_mode": self.delete_original_mode.get(),
            "file_suffix": self.file_suffix.get(),
            "max_workers": self.max_workers.get(),
            "batch_size": self.batch_size.get(),
            "created_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "use_test_output": self.use_test_output.get(),
            "test_output_folder": self.test_output_folder.get()
        }
        
        # プリセットをファイルに保存
        preset_path = os.path.join(self.preset_dir, f"{preset_name}.json")
        try:
            with open(preset_path, 'w', encoding='utf-8') as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
            
            # プリセットリストを更新
            self.populate_preset_list(listbox)
            # メニューを更新
            self.update_preset_menu_all()
            
            messagebox.showinfo("保存完了", f"プリセット '{preset_name}' を保存しました")
        except Exception as e:
            messagebox.showerror("エラー", f"プリセット保存中にエラーが発生しました: {e}")

    def load_preset_from_manager(self, listbox):
        """プリセット管理画面からプリセットを読み込む"""
        selection = listbox.curselection()
        if not selection:
            messagebox.showinfo("選択エラー", "プリセットを選択してください")
            return
        
        preset_name = listbox.get(selection[0])
        if preset_name == "保存されたプリセットはありません":
            return
        
        self.apply_preset(preset_name)

    def delete_preset(self, listbox):
        """選択したプリセットを削除"""
        selection = listbox.curselection()
        if not selection:
            messagebox.showinfo("選択エラー", "削除するプリセットを選択してください")
            return
        
        preset_name = listbox.get(selection[0])
        if preset_name == "保存されたプリセットはありません":
            return
        
        if messagebox.askyesno("削除確認", f"プリセット '{preset_name}' を削除してもよろしいですか？"):
            preset_path = os.path.join(self.preset_dir, f"{preset_name}.json")
            try:
                os.remove(preset_path)
                # プリセットリストを更新
                self.populate_preset_list(listbox)
                # メニューを更新
                self.update_preset_menu_all()
                
                messagebox.showinfo("削除完了", f"プリセット '{preset_name}' を削除しました")
            except Exception as e:
                messagebox.showerror("エラー", f"プリセット削除中にエラーが発生しました: {e}")

    def rename_preset(self, listbox):
        """選択したプリセットの名前を変更"""
        selection = listbox.curselection()
        if not selection:
            messagebox.showinfo("選択エラー", "名前を変更するプリセットを選択してください")
            return
        
        old_name = listbox.get(selection[0])
        if old_name == "保存されたプリセットはありません":
            return
        
        new_name = simpledialog.askstring("名前変更", "新しいプリセット名を入力してください:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return
        
        # ファイル名に使用できない文字を置換
        new_name = new_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
        
        old_path = os.path.join(self.preset_dir, f"{old_name}.json")
        new_path = os.path.join(self.preset_dir, f"{new_name}.json")
        
        try:
            # ファイル名を変更
            os.rename(old_path, new_path)
            # プリセットリストを更新
            self.populate_preset_list(listbox)
            # メニューを更新
            self.update_preset_menu_all()
            
            messagebox.showinfo("名前変更完了", f"プリセット名を '{old_name}' から '{new_name}' に変更しました")
        except Exception as e:
            messagebox.showerror("エラー", f"プリセット名変更中にエラーが発生しました: {e}")

    def update_preset_menu_all(self):
        """すべてのプリセットメニューを更新"""
        # メインメニューのプリセットメニューを更新
        preset_menu = self.file_menu.nametowidget(self.file_menu.entrycget("プリセット", "menu"))
        self.update_preset_menu(preset_menu)

def main():
    try:
        app = CaesiumCLTGUI()
        app.mainloop()
    except Exception as e:
        logger.critical(f"アプリケーション起動エラー: {e}", exc_info=True)
        # アプリケーションインスタンスがある場合はログを保存
        if 'app' in locals() and hasattr(app, 'save_logs_to_file'):
            try:
                app.save_logs_to_file()
            except Exception:
                logger.exception("起動エラー時のログ保存に失敗")
        messagebox.showerror("Critical Error", f"アプリケーション起動に失敗しました。\n\n{e}")

if __name__ == "__main__":
    main()
