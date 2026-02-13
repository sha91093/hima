"""
地番名寄せシステム GUI

CustomTkinterが利用可能ならモダンなUI、
なければ標準tkinterにフォールバック。
低スペックPCでも軽快に動作する設計。
"""

import csv
import os
import threading
from pathlib import Path

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    BaseWindow = ctk.CTk
    BaseFrame = ctk.CTkFrame
    BaseButton = ctk.CTkButton
    BaseLabel = ctk.CTkLabel
    BaseEntry = ctk.CTkEntry
    BaseOptionMenu = ctk.CTkOptionMenu
    BaseScrollableFrame = ctk.CTkScrollableFrame
    HAS_CTK = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk
    BaseWindow = tk.Tk
    BaseFrame = ttk.Frame
    BaseButton = ttk.Button
    BaseLabel = ttk.Label
    BaseEntry = ttk.Entry
    BaseOptionMenu = ttk.Combobox
    BaseScrollableFrame = ttk.Frame
    HAS_CTK = False

import tkinter as tk
from tkinter import filedialog, messagebox

from .normalizer import normalize_single
from .converter import (
    read_excel_column, read_csv_column, read_master,
    convert_and_compare, export_comparison_csv,
)
from .matcher import SISMatcher, MatchStatus

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# --- 色定義 ---
COLORS = {
    MatchStatus.EXACT: "#c8e6c9",      # 緑: 完全一致
    MatchStatus.INFERRED: "#fff9c4",   # 黄: 推測成功
    MatchStatus.UNMATCHED: "#ffcdd2",  # 赤: 判定不能
}

STATUS_LABELS = {
    MatchStatus.EXACT: "完全一致",
    MatchStatus.INFERRED: "推測成功",
    MatchStatus.UNMATCHED: "判定不能",
}


class LandParcelApp:
    """メインアプリケーション"""

    def __init__(self):
        self.root = BaseWindow() if HAS_CTK else tk.Tk()
        self.root.title("地番名寄せシステム")
        self.root.geometry("1100x700")

        # 状態変数
        self.input_rows = []
        self.master_data = None
        self.matcher = None
        self.comparison_results = []
        self.match_results = []

        # 設定変数
        self.chiban_column_var = tk.StringVar(value="0")
        self.master_chiban_col_var = tk.StringVar(value="0")
        self.master_oaza_col_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        """UIを構築する。"""
        # --- ヘッダー ---
        header = self._frame(self.root)
        header.pack(fill="x", padx=10, pady=5)
        self._label(header, text="地番名寄せシステム",
                    font=("", 16, "bold")).pack(side="left")

        # --- ファイル選択エリア ---
        file_frame = self._frame(self.root)
        file_frame.pack(fill="x", padx=10, pady=5)

        # 入力ファイル
        input_row = self._frame(file_frame)
        input_row.pack(fill="x", pady=2)
        self._label(input_row, text="入力Excel/CSV:").pack(side="left")
        self.input_path_var = tk.StringVar()
        self._entry(input_row, textvariable=self.input_path_var,
                    width=50).pack(side="left", padx=5, fill="x", expand=True)
        self._button(input_row, text="参照...",
                     command=self._select_input).pack(side="left")
        self._label(input_row, text="地番列:").pack(side="left", padx=(10, 0))
        self._entry(input_row, textvariable=self.chiban_column_var,
                    width=10).pack(side="left", padx=2)

        # マスターファイル
        master_row = self._frame(file_frame)
        master_row.pack(fill="x", pady=2)
        self._label(master_row, text="SISマスターCSV:").pack(side="left")
        self.master_path_var = tk.StringVar()
        self._entry(master_row, textvariable=self.master_path_var,
                    width=50).pack(side="left", padx=5, fill="x", expand=True)
        self._button(master_row, text="参照...",
                     command=self._select_master).pack(side="left")
        self._label(master_row, text="地番列:").pack(side="left", padx=(10, 0))
        self._entry(master_row, textvariable=self.master_chiban_col_var,
                    width=6).pack(side="left", padx=2)
        self._label(master_row, text="大字列:").pack(side="left", padx=(5, 0))
        self._entry(master_row, textvariable=self.master_oaza_col_var,
                    width=6).pack(side="left", padx=2)

        # 実行ボタン
        btn_row = self._frame(file_frame)
        btn_row.pack(fill="x", pady=5)
        self._button(btn_row, text="変換＆突合を実行",
                     command=self._run_conversion).pack(side="left")
        self._button(btn_row, text="結果をCSV出力",
                     command=self._export_results).pack(side="left", padx=10)
        self._button(btn_row, text="SISインポート用CSV出力",
                     command=self._export_sis_csv).pack(side="left")

        # --- 統計情報 ---
        self.stats_var = tk.StringVar(value="ファイルを選択して「変換＆突合を実行」を押してください")
        stats_label = self._label(self.root, textvariable=self.stats_var)
        stats_label.pack(fill="x", padx=10, pady=2)

        # --- 結果テーブル ---
        table_frame = self._frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Treeview（全環境共通で使用）
        columns = ("status", "raw", "normalized", "matched", "confidence")
        self.tree = ttk.Treeview(table_frame, columns=columns,
                                 show="headings", selectmode="browse")
        self.tree.heading("status", text="判定")
        self.tree.heading("raw", text="変換前（原文）")
        self.tree.heading("normalized", text="正規化後")
        self.tree.heading("matched", text="SIS一致先")
        self.tree.heading("confidence", text="信頼度")

        self.tree.column("status", width=80, anchor="center")
        self.tree.column("raw", width=250)
        self.tree.column("normalized", width=250)
        self.tree.column("matched", width=250)
        self.tree.column("confidence", width=80, anchor="center")

        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical",
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_y.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")

        # 行色付け用タグ
        self.tree.tag_configure("exact", background=COLORS[MatchStatus.EXACT])
        self.tree.tag_configure("inferred", background=COLORS[MatchStatus.INFERRED])
        self.tree.tag_configure("unmatched", background=COLORS[MatchStatus.UNMATCHED])

        # ダブルクリックで手動マッチング
        self.tree.bind("<Double-1>", self._on_double_click)

        # --- 手動マッチングエリア ---
        manual_frame = self._frame(self.root)
        manual_frame.pack(fill="x", padx=10, pady=5)
        self._label(manual_frame, text="マスター検索:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = self._entry(manual_frame, textvariable=self.search_var,
                                        width=30)
        self.search_entry.pack(side="left", padx=5)
        self._button(manual_frame, text="検索",
                     command=self._search_master).pack(side="left")
        self._button(manual_frame, text="選択した候補で確定",
                     command=self._apply_manual_match).pack(side="left", padx=10)

        # 検索結果リスト
        self.search_listbox = tk.Listbox(manual_frame, width=40, height=5)
        self.search_listbox.pack(side="left", padx=5, fill="y")

        # ステータスバー
        self.statusbar_var = tk.StringVar(value="準備完了")
        status_bar = self._label(self.root, textvariable=self.statusbar_var,
                                  anchor="w")
        status_bar.pack(fill="x", padx=10, pady=2)

    # --- UI ヘルパー（CustomTkinter / tkinter 互換） ---
    def _frame(self, parent, **kw):
        if HAS_CTK:
            return ctk.CTkFrame(parent, **kw)
        return ttk.Frame(parent, **kw)

    def _label(self, parent, **kw):
        if HAS_CTK:
            return ctk.CTkLabel(parent, **kw)
        return ttk.Label(parent, **kw)

    def _button(self, parent, **kw):
        if HAS_CTK:
            return ctk.CTkButton(parent, **kw)
        return ttk.Button(parent, **kw)

    def _entry(self, parent, **kw):
        if HAS_CTK:
            return ctk.CTkEntry(parent, **kw)
        return ttk.Entry(parent, **kw)

    # --- ファイル選択 ---
    def _select_input(self):
        path = filedialog.askopenfilename(
            title="入力ファイルを選択",
            filetypes=[
                ("Excel/CSV", "*.xlsx *.xls *.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("すべて", "*.*"),
            ]
        )
        if path:
            self.input_path_var.set(path)

    def _select_master(self):
        path = filedialog.askopenfilename(
            title="SISマスターを選択",
            filetypes=[
                ("Excel/CSV", "*.xlsx *.xls *.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("すべて", "*.*"),
            ]
        )
        if path:
            self.master_path_var.set(path)

    # --- 変換＆突合 ---
    def _run_conversion(self):
        input_path = self.input_path_var.get().strip()
        master_path = self.master_path_var.get().strip()

        if not input_path:
            messagebox.showwarning("警告", "入力ファイルを選択してください。")
            return

        self.statusbar_var.set("処理中...")
        self.root.update_idletasks()

        try:
            # 列番号の解析
            chiban_col = self._parse_column(self.chiban_column_var.get())

            # 入力ファイル読み込み
            if input_path.lower().endswith((".xlsx", ".xls")):
                if not HAS_PANDAS:
                    messagebox.showerror(
                        "エラー",
                        "Excelの読み込みにはpandasが必要です。\n"
                        "pip install pandas openpyxl"
                    )
                    return
                self.input_rows = read_excel_column(input_path, chiban_column=chiban_col)
            else:
                self.input_rows = read_csv_column(input_path, chiban_column=chiban_col)

            # マスター読み込み
            oaza_list = None
            if master_path:
                master_chiban_col = self._parse_column(self.master_chiban_col_var.get())
                master_oaza_col_str = self.master_oaza_col_var.get().strip()
                master_oaza_col = self._parse_column(master_oaza_col_str) if master_oaza_col_str else None

                self.master_data = read_master(
                    master_path,
                    chiban_column=master_chiban_col,
                    oaza_column=master_oaza_col,
                )
                oaza_list = self.master_data["oaza_list"]
                self.matcher = SISMatcher(
                    self.master_data["parcels"],
                    oaza_list,
                )

            # 変換
            self.comparison_results = convert_and_compare(
                self.input_rows, oaza_list=oaza_list
            )

            # 突合
            self.match_results = []
            if self.matcher:
                for comp in self.comparison_results:
                    for parcel in comp["normalized"]:
                        result = self.matcher.match_single(parcel)
                        result["row"] = comp["row"]
                        self.match_results.append(result)
            else:
                # マスターなしの場合: 正規化結果だけ表示
                for comp in self.comparison_results:
                    for parcel in comp["normalized"]:
                        self.match_results.append({
                            "input": parcel,
                            "status": MatchStatus.UNMATCHED,
                            "matched_to": None,
                            "candidates": [],
                            "confidence": 0.0,
                            "row": comp["row"],
                        })

            # 結果をテーブルに表示
            self._populate_table()

            # 統計表示
            if self.matcher:
                stats = self.matcher.get_statistics(self.match_results)
                self.stats_var.set(
                    f"合計: {stats['total']}件 | "
                    f"完全一致: {stats['exact']}件 ({stats['exact_rate']:.1f}%) | "
                    f"推測成功: {stats['inferred']}件 | "
                    f"判定不能: {stats['unmatched']}件 | "
                    f"解決率: {stats['resolved_rate']:.1f}%"
                )
            else:
                self.stats_var.set(
                    f"正規化完了: {len(self.match_results)}件 "
                    f"(マスター未指定のため突合なし)"
                )

            self.statusbar_var.set("完了")

        except Exception as e:
            messagebox.showerror("エラー", f"処理中にエラーが発生しました:\n{e}")
            self.statusbar_var.set("エラー発生")

    def _parse_column(self, value: str) -> str | int:
        """列指定の文字列をパースする。数字なら int、それ以外は列名。"""
        value = value.strip()
        if value.isdigit():
            return int(value)
        return value

    def _populate_table(self):
        """結果をTreeviewに表示する。"""
        # 既存の行を全クリア
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, result in enumerate(self.match_results):
            status = result["status"]
            status_label = STATUS_LABELS.get(status, "?")
            raw = result["input"].get("raw", "")
            normalized = result["input"].get("full", "")
            matched = result.get("matched_to", "") or ""
            confidence = f"{result['confidence']:.0%}" if result["confidence"] > 0 else ""

            tag = status.value  # "exact", "inferred", "unmatched"
            self.tree.insert("", "end", iid=str(idx),
                             values=(status_label, raw, normalized,
                                     matched, confidence),
                             tags=(tag,))

    # --- 手動マッチング ---
    def _on_double_click(self, event):
        """判定不能の行をダブルクリックで手動マッチングモードに。"""
        selection = self.tree.selection()
        if not selection:
            return

        idx = int(selection[0])
        result = self.match_results[idx]

        # 検索窓に正規化後の値をセット
        self.search_var.set(result["input"].get("full", ""))

        # 候補があれば表示
        self.search_listbox.delete(0, tk.END)
        for c in result.get("candidates", []):
            self.search_listbox.insert(
                tk.END, f"{c['parcel']} (類似度: {c['score']:.0%})"
            )

    def _search_master(self):
        """マスターデータを検索する。"""
        if not self.matcher:
            messagebox.showinfo("情報", "マスターデータが読み込まれていません。")
            return

        query = self.search_var.get().strip()
        if not query:
            return

        results = self.matcher.search_master(query, max_results=20)
        self.search_listbox.delete(0, tk.END)
        for p in results:
            self.search_listbox.insert(tk.END, p)

    def _apply_manual_match(self):
        """検索結果リストで選択した候補を、選択中の行に適用する。"""
        tree_selection = self.tree.selection()
        list_selection = self.search_listbox.curselection()

        if not tree_selection:
            messagebox.showinfo("情報", "テーブルから対象行を選択してください。")
            return
        if not list_selection:
            messagebox.showinfo("情報", "候補リストから地番を選択してください。")
            return

        idx = int(tree_selection[0])
        selected_text = self.search_listbox.get(list_selection[0])
        # "(類似度: xx%)" の部分を除去
        parcel = selected_text.split(" (")[0].strip()

        # 結果を更新
        self.match_results[idx]["status"] = MatchStatus.EXACT
        self.match_results[idx]["matched_to"] = parcel
        self.match_results[idx]["confidence"] = 1.0

        # テーブルを更新
        self.tree.item(str(idx), values=(
            STATUS_LABELS[MatchStatus.EXACT],
            self.match_results[idx]["input"].get("raw", ""),
            self.match_results[idx]["input"].get("full", ""),
            parcel,
            "100%",
        ), tags=("exact",))

        self.statusbar_var.set(f"行 {idx} を手動マッチングしました: {parcel}")

    # --- 出力 ---
    def _export_results(self):
        """比較結果をCSV出力する。"""
        if not self.match_results:
            messagebox.showinfo("情報", "先に変換＆突合を実行してください。")
            return

        path = filedialog.asksaveasfilename(
            title="結果CSVを保存",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="cp932", newline="",
                      errors="replace") as f:
                writer = csv.writer(f)
                writer.writerow(["判定", "変換前", "正規化後", "SIS一致先",
                                 "信頼度", "元の行番号"])
                for r in self.match_results:
                    writer.writerow([
                        STATUS_LABELS.get(r["status"], "?"),
                        r["input"].get("raw", ""),
                        r["input"].get("full", ""),
                        r.get("matched_to", ""),
                        f"{r['confidence']:.0%}" if r["confidence"] > 0 else "",
                        r.get("row", ""),
                    ])

            messagebox.showinfo("完了", f"CSVを保存しました:\n{path}")
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗しました:\n{e}")

    def _export_sis_csv(self):
        """SISインポート用のCSVを出力する（一致・推測成功のもののみ）。"""
        if not self.match_results:
            messagebox.showinfo("情報", "先に変換＆突合を実行してください。")
            return

        resolved = [r for r in self.match_results
                    if r["status"] in (MatchStatus.EXACT, MatchStatus.INFERRED)
                    and r.get("matched_to")]

        if not resolved:
            messagebox.showinfo("情報", "一致する地番がありません。")
            return

        path = filedialog.asksaveasfilename(
            title="SISインポート用CSVを保存",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="cp932", newline="",
                      errors="replace") as f:
                writer = csv.writer(f)
                writer.writerow(["地番"])
                seen = set()
                for r in resolved:
                    parcel = r["matched_to"]
                    if parcel not in seen:
                        writer.writerow([parcel])
                        seen.add(parcel)

            messagebox.showinfo(
                "完了",
                f"SISインポート用CSVを保存しました:\n{path}\n"
                f"({len(seen)}件の地番)"
            )
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗しました:\n{e}")

    def run(self):
        """アプリケーションを起動する。"""
        self.root.mainloop()
