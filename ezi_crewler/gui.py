"""Tkinter interface for crawling, visualizing, and comparing websites."""

from __future__ import annotations

import csv
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .crawler import crawl
from .models import CrawlProgress, CrawlRun, Page
from .parsing import normalize_url
from .ranking import RankingResult, analyze_graph


class CrawlerApp:
    MAX_GRAPH_EDGES = 150

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EZI Crewler — badanie struktury WWW")
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        self.runs: List[CrawlRun] = []
        self.active_run: Optional[CrawlRun] = None
        self.stop_event: Optional[threading.Event] = None
        self.worker: Optional[threading.Thread] = None
        self.events: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self.last_crawl_snapshot: Optional[
            Tuple[CrawlRun, Dict[str, Page], set[Tuple[str, str]]]
        ] = None

        self._build_ui()
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        controls = ttk.Frame(self.root, padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Adres startowy:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value="https://example.com")
        ttk.Entry(controls, textvariable=self.url_var, width=58).grid(
            row=0, column=1, columnspan=5, sticky="ew", padx=(6, 12)
        )
        ttk.Label(controls, text="Głębokość:").grid(row=0, column=6, sticky="e")
        self.depth_var = tk.StringVar(value="3")
        ttk.Spinbox(controls, from_=0, to=10, textvariable=self.depth_var, width=5).grid(
            row=0, column=7, padx=6
        )
        ttk.Label(controls, text="Limit stron:").grid(row=0, column=8, sticky="e")
        self.limit_var = tk.StringVar(value="50")
        ttk.Spinbox(controls, from_=1, to=500, textvariable=self.limit_var, width=6).grid(
            row=0, column=9, padx=6
        )

        ttk.Label(controls, text="Strategia (hops):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.strategy_var = tk.StringVar(value="Breadth first")
        ttk.Combobox(
            controls,
            textvariable=self.strategy_var,
            values=("Breadth first", "Depth first"),
            state="readonly",
            width=17,
        ).grid(row=1, column=1, sticky="w", padx=(6, 12), pady=(8, 0))
        ttk.Label(controls, text="Tryb:").grid(row=1, column=2, sticky="e", pady=(8, 0))
        self.mode_var = tk.StringVar(value="server")
        ttk.Combobox(
            controls, textvariable=self.mode_var, values=("server", "web"), state="readonly", width=10
        ).grid(row=1, column=3, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(controls, text="Using:").grid(row=1, column=4, sticky="e", pady=(8, 0))
        self.using_var = tk.StringVar(value="images+hyperlinks")
        ttk.Combobox(
            controls,
            textvariable=self.using_var,
            values=("images+hyperlinks", "all links"),
            state="readonly",
            width=20,
        ).grid(row=1, column=5, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(controls, text="Opóźnienie (s):").grid(row=1, column=6, sticky="e", pady=(8, 0))
        self.delay_var = tk.StringVar(value="0.3")
        ttk.Spinbox(
            controls, from_=0, to=10, increment=0.1, textvariable=self.delay_var, width=6
        ).grid(row=1, column=7, padx=6, pady=(8, 0))

        self.start_button = ttk.Button(controls, text="Rozpocznij crawl", command=self._start_crawl)
        self.start_button.grid(row=1, column=8, padx=(8, 4), pady=(8, 0))
        self.stop_button = ttk.Button(
            controls, text="Anuluj", command=self._cancel_crawl, state="disabled"
        )
        self.stop_button.grid(row=1, column=9, pady=(8, 0))
        controls.columnconfigure(1, weight=1)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        crawl_tab = ttk.Frame(self.notebook, padding=8)
        compare_tab = ttk.Frame(self.notebook, padding=8)
        ranking_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(crawl_tab, text="Crawl")
        self.notebook.add(compare_tab, text="Porównanie")
        self.notebook.add(ranking_tab, text="Ranking grafu")

        self.metrics_var = tk.StringVar(value="Wprowadź adres i rozpocznij crawl.")
        ttk.Label(crawl_tab, textvariable=self.metrics_var, wraplength=1080).pack(
            fill="x", pady=(0, 8)
        )
        graph_frame = ttk.Frame(crawl_tab)
        graph_frame.pack(fill="both", expand=True)
        graph_controls = ttk.Frame(graph_frame)
        graph_controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.show_crawl_edges_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            graph_controls,
            text=f"Pokaż połączenia (maks. {self.MAX_GRAPH_EDGES})",
            variable=self.show_crawl_edges_var,
            command=self._redraw_last_crawl_graph,
        ).pack(side="left")
        ttk.Label(graph_controls, text="Przesuwanie: przeciągnij graf myszą; przewijaj kółkiem.").pack(
            side="right"
        )
        self.canvas = tk.Canvas(graph_frame, background="white", highlightthickness=1)
        y_scroll = ttk.Scrollbar(graph_frame, orient="vertical", command=self.canvas.yview)
        x_scroll = ttk.Scrollbar(graph_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll.grid(row=2, column=0, sticky="ew")
        graph_frame.rowconfigure(1, weight=1)
        graph_frame.columnconfigure(0, weight=1)
        self._enable_canvas_navigation(self.canvas)

        log_frame = ttk.LabelFrame(crawl_tab, text="Dziennik", padding=5)
        log_frame.pack(fill="x", pady=(8, 0))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical")
        self.log_text = tk.Text(log_frame, height=5, wrap="word", state="disabled")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.configure(command=self.log_text.yview)
        self.log_text.pack(side="left", fill="x", expand=True)
        log_scroll.pack(side="right", fill="y")

        self._build_compare_tab(compare_tab)
        self._build_ranking_tab(ranking_tab)
        self.status_var = tk.StringVar(value="Gotowy")
        status = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w")
        status.pack(fill="x", side="bottom")

    def _build_compare_tab(self, tab: ttk.Frame) -> None:
        selectors = ttk.Frame(tab)
        selectors.pack(fill="x")
        ttk.Label(selectors, text="Sesja A:").pack(side="left")
        self.run_a_var = tk.StringVar()
        self.run_a_combo = ttk.Combobox(selectors, textvariable=self.run_a_var, state="readonly", width=35)
        self.run_a_combo.pack(side="left", padx=6)
        ttk.Label(selectors, text="Sesja B:").pack(side="left", padx=(12, 0))
        self.run_b_var = tk.StringVar()
        self.run_b_combo = ttk.Combobox(selectors, textvariable=self.run_b_var, state="readonly", width=35)
        self.run_b_combo.pack(side="left", padx=6)
        ttk.Button(selectors, text="Porównaj", command=self._compare_runs).pack(side="left", padx=8)
        ttk.Button(selectors, text="Zapisz CSV", command=self._save_csv).pack(side="right")

        columns = ("measure", "run_a", "run_b", "difference")
        self.compare_tree = ttk.Treeview(tab, columns=columns, show="headings", height=10)
        for column, title, width in (
            ("measure", "Metryka", 260),
            ("run_a", "Sesja A", 280),
            ("run_b", "Sesja B", 280),
            ("difference", "Różnica B − A", 180),
        ):
            self.compare_tree.heading(column, text=title)
            self.compare_tree.column(column, width=width, anchor="w")
        self.compare_tree.pack(fill="x", pady=12)
        self.compare_note = tk.StringVar(
            value="Uruchom co najmniej dwa crawle, aby porównać ich strukturę i zawartość."
        )
        ttk.Label(tab, textvariable=self.compare_note, wraplength=1050).pack(fill="x", anchor="w")

    def _build_ranking_tab(self, tab: ttk.Frame) -> None:
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="Źródło crawl:").pack(side="left")
        self.ranking_run_var = tk.StringVar()
        self.ranking_run_combo = ttk.Combobox(
            toolbar, textvariable=self.ranking_run_var, state="readonly", width=38
        )
        self.ranking_run_combo.pack(side="left", padx=6)
        ttk.Button(toolbar, text="Wczytaj krawędzie", command=self._load_ranking_edges).pack(
            side="left", padx=4
        )
        ttk.Button(toolbar, text="Oblicz ranking", command=self._analyze_ranking).pack(
            side="left", padx=4
        )
        ttk.Button(toolbar, text="Eksportuj CSV", command=self._save_ranking_csv).pack(
            side="right"
        )

        input_frame = ttk.LabelFrame(
            tab, text="Krawędzie grafu — jeden wiersz: adres źródłowy -> adres docelowy", padding=6
        )
        input_frame.pack(fill="x", pady=(0, 8))
        self.ranking_edges_text = tk.Text(input_frame, height=5, wrap="none")
        edge_scroll = ttk.Scrollbar(
            input_frame, orient="vertical", command=self.ranking_edges_text.yview
        )
        self.ranking_edges_text.configure(yscrollcommand=edge_scroll.set)
        self.ranking_edges_text.pack(side="left", fill="x", expand=True)
        edge_scroll.pack(side="right", fill="y")

        self.ranking_requirements_var = tk.StringVar(
            value="Wczytaj krawędzie z crawl lub wklej pary adresów i wybierz „Oblicz ranking”."
        )
        info_frame = ttk.Frame(tab)
        info_frame.pack(fill="x", pady=(0, 8))
        self.ranking_info_text = tk.Text(info_frame, height=5, wrap="word", state="disabled")
        info_scroll = ttk.Scrollbar(info_frame, orient="vertical", command=self.ranking_info_text.yview)
        self.ranking_info_text.configure(yscrollcommand=info_scroll.set)
        self.ranking_info_text.pack(side="left", fill="x", expand=True)
        info_scroll.pack(side="right", fill="y")
        self._set_ranking_info(self.ranking_requirements_var.get())
        self.ranking_notebook = ttk.Notebook(tab)
        self.ranking_notebook.pack(fill="both", expand=True)

        ranking_view = ttk.Frame(self.ranking_notebook, padding=5)
        graph_view = ttk.Frame(self.ranking_notebook, padding=5)
        adjacency_view = ttk.Frame(self.ranking_notebook, padding=5)
        weighted_view = ttk.Frame(self.ranking_notebook, padding=5)
        self.ranking_notebook.add(ranking_view, text="Ranking")
        self.ranking_notebook.add(graph_view, text="Graf z prestiżem")
        self.ranking_notebook.add(adjacency_view, text="Macierz A")
        self.ranking_notebook.add(weighted_view, text="Macierz A/Nv")

        graph_controls = ttk.Frame(graph_view)
        graph_controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Label(graph_controls, text="Prestiż wyświetlany na grafie:").pack(side="left")
        self.ranking_metric_var = tk.StringVar(value="Wektor własny A/Nv")
        metric_combo = ttk.Combobox(
            graph_controls,
            textvariable=self.ranking_metric_var,
            values=("Prestiż A", "Prestiż A/Nv", "Wektor własny A/Nv"),
            state="readonly",
            width=24,
        )
        metric_combo.pack(side="left", padx=6)
        metric_combo.bind("<<ComboboxSelected>>", self._redraw_ranked_graph)
        self.show_ranking_edges_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            graph_controls,
            text=f"Pokaż połączenia (maks. {self.MAX_GRAPH_EDGES})",
            variable=self.show_ranking_edges_var,
            command=self._redraw_current_ranking_graph,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(graph_controls, text="Przeciągnij graf, aby go przesunąć; kółko myszy przewija.").pack(
            side="right"
        )

        columns = (
            "rank_raw",
            "rank_weighted",
            "rank_eigen",
            "address",
            "incoming",
            "raw",
            "weighted",
            "eigen",
        )
        self.ranking_tree = ttk.Treeview(ranking_view, columns=columns, show="headings")
        for column, title, width in (
            ("rank_raw", "Ranga A", 65),
            ("rank_weighted", "Ranga A/Nv", 75),
            ("rank_eigen", "Ranga eigen", 80),
            ("address", "Adres / wierzchołek", 400),
            ("incoming", "Linki wchodzące", 100),
            ("raw", "Prestiż A", 105),
            ("weighted", "Prestiż A/Nv", 110),
            ("eigen", "Wektor własny", 110),
        ):
            self.ranking_tree.heading(column, text=title)
            self.ranking_tree.column(column, width=width, anchor="w")
        ranking_scroll = ttk.Scrollbar(
            ranking_view, orient="vertical", command=self.ranking_tree.yview
        )
        ranking_x_scroll = ttk.Scrollbar(
            ranking_view, orient="horizontal", command=self.ranking_tree.xview
        )
        self.ranking_tree.configure(
            yscrollcommand=ranking_scroll.set, xscrollcommand=ranking_x_scroll.set
        )
        self.ranking_tree.grid(row=0, column=0, sticky="nsew")
        ranking_scroll.grid(row=0, column=1, sticky="ns")
        ranking_x_scroll.grid(row=1, column=0, sticky="ew")
        ranking_view.rowconfigure(0, weight=1)
        ranking_view.columnconfigure(0, weight=1)

        self.ranking_graph = tk.Canvas(
            graph_view, background="white", highlightthickness=1, scrollregion=(0, 0, 1100, 700)
        )
        graph_y_scroll = ttk.Scrollbar(
            graph_view, orient="vertical", command=self.ranking_graph.yview
        )
        graph_x_scroll = ttk.Scrollbar(
            graph_view, orient="horizontal", command=self.ranking_graph.xview
        )
        self.ranking_graph.configure(
            yscrollcommand=graph_y_scroll.set, xscrollcommand=graph_x_scroll.set
        )
        self.ranking_graph.grid(row=1, column=0, sticky="nsew")
        graph_y_scroll.grid(row=1, column=1, sticky="ns")
        graph_x_scroll.grid(row=2, column=0, sticky="ew")
        graph_view.rowconfigure(1, weight=1)
        graph_view.columnconfigure(0, weight=1)
        self._enable_canvas_navigation(self.ranking_graph)

        self.adjacency_text = self._make_matrix_view(adjacency_view)
        self.weighted_matrix_text = self._make_matrix_view(weighted_view)
        self.ranking_result: Optional[RankingResult] = None

    @staticmethod
    def _make_matrix_view(parent: ttk.Frame) -> tk.Text:
        matrix_text = tk.Text(parent, wrap="none", font=("Consolas", 9), state="disabled")
        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=matrix_text.yview)
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=matrix_text.xview)
        matrix_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        matrix_text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        return matrix_text

    def _load_ranking_edges(self) -> None:
        run = next(
            (item for item in self.runs if item.name == self.ranking_run_var.get()), None
        )
        if not run:
            messagebox.showinfo("Brak crawl", "Najpierw wykonaj crawl lub wybierz jego sesję.")
            return
        self.ranking_edges_text.delete("1.0", "end")
        for source, target in sorted(run.hyperlinks):
            self.ranking_edges_text.insert("end", f"{source} -> {target}\n")
        self._set_ranking_info(
            f"Wczytano {len(run.hyperlinks)} krawędzi-hyperlinków z sesji „{run.name}”. "
            "Możesz też edytować lub wkleić własną listę przed obliczeniem."
        )

    def _analyze_ranking(self) -> None:
        edges = []
        for line_number, line in enumerate(
            self.ranking_edges_text.get("1.0", "end").splitlines(), start=1
        ):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "->" in line:
                source, target = line.split("->", maxsplit=1)
            elif ";" in line:
                source, target = line.split(";", maxsplit=1)
            elif "\t" in line:
                source, target = line.split("\t", maxsplit=1)
            else:
                messagebox.showerror(
                    "Nieprawidłowa krawędź",
                    f"Wiersz {line_number}: użyj formatu „źródło -> cel”.",
                )
                return
            if not source.strip() or not target.strip():
                messagebox.showerror(
                    "Nieprawidłowa krawędź", f"Wiersz {line_number}: brakuje adresu źródła lub celu."
                )
                return
            edges.append((source.strip(), target.strip()))
        if not edges:
            messagebox.showinfo("Brak danych", "Wklej lub wczytaj co najmniej jedną krawędź.")
            return

        self.ranking_result = analyze_graph(edges)
        self._display_ranking(self.ranking_result)

    def _display_ranking(self, result: RankingResult) -> None:
        for item in self.ranking_tree.get_children():
            self.ranking_tree.delete(item)
        raw_order = sorted(
            result.nodes, key=lambda node: result.raw_prestige[node], reverse=True
        )
        weighted_order = sorted(
            result.nodes, key=lambda node: result.weighted_prestige[node], reverse=True
        )
        eigen_order = sorted(
            result.nodes, key=lambda node: result.eigenvector_prestige[node], reverse=True
        )
        raw_ranks = {node: rank for rank, node in enumerate(raw_order, start=1)}
        weighted_ranks = {node: rank for rank, node in enumerate(weighted_order, start=1)}
        eigen_ranks = {node: rank for rank, node in enumerate(eigen_order, start=1)}
        for node in eigen_order:
            self.ranking_tree.insert(
                "",
                "end",
                values=(
                    raw_ranks[node],
                    weighted_ranks[node],
                    eigen_ranks[node],
                    node,
                    result.in_degrees[node],
                    f"{result.raw_prestige[node]:.8f}",
                    f"{result.weighted_prestige[node]:.8f}",
                    f"{result.eigenvector_prestige[node]:.8f}",
                ),
            )

        cycle_text = " → ".join(result.cycle) if result.cycle else "brak"
        convergence = (
            f"A: {result.raw_iterations} iteracji"
            f"{'' if result.raw_converged else ' (brak zbieżności)'}; "
            f"A/Nv: {result.weighted_iterations} iteracji"
            f"{'' if result.weighted_converged else ' (brak zbieżności)'}."
        )
        methodology = (
            "Początkowy prestiż każdego wierzchołka: 1 (wektor jest normalizowany do sumy 1). "
            "W cyklach stosowana jest iteracja potęgowa na A + I: dodanie I nie zmienia "
            "wektorów własnych, a ogranicza oscylacje. Macierz ma konwencję A[cel][źródło]; "
            "w A/Nv każda kolumna źródła jest dzielona przez liczbę jego linków wychodzących. "
            "Wyniki A/Nv i wektora własnego powinny dać ten sam ranking. "
            "Praktycznie zwykle lepsza jest macierz A/Nv: dzieli wpływ strony między jej linki "
            "wychodzące, zamiast premiować ją bez ograniczeń za wiele linków."
        )
        self._set_ranking_info(
            "\n".join(result.requirement_messages)
            + f"\nCykl: {cycle_text}. Wartości własne: λ(A)≈{result.raw_eigenvalue:.6f}, "
            f"λ(A/Nv)≈{result.weighted_eigenvalue:.6f}. {convergence}\n"
            + methodology
        )
        self._render_matrix(self.adjacency_text, result.nodes, result.adjacency, integral=True)
        self._render_matrix(
            self.weighted_matrix_text, result.nodes, result.weighted_adjacency, integral=False
        )
        self._draw_ranked_graph(result)

    @staticmethod
    def _render_matrix(
        widget: tk.Text, nodes: List[str], matrix: List[List[float]], integral: bool
    ) -> None:
        max_visible = 60
        visible_nodes = nodes[:max_visible]
        prefix = "Wiersz = cel; kolumna = źródło. Kolejność wierszy/kolumn:\n"
        prefix += "\n".join(f"{index}: {node}" for index, node in enumerate(visible_nodes))
        prefix += "\n\n"
        if len(nodes) > max_visible:
            prefix += f"Podgląd {max_visible} z {len(nodes)} wierzchołków.\n"
        column_width = 5 if integral else 7
        prefix += "      " + " ".join(
            f"{index:>{column_width}}" for index in range(len(visible_nodes))
        ) + "\n"
        for row_index, row in enumerate(matrix[:max_visible]):
            values = (
                " ".join(f"{int(value):>5}" for value in row[:max_visible])
                if integral
                else " ".join(f"{value:7.4f}" for value in row[:max_visible])
            )
            prefix += f"{row_index:>5} {values}\n"
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", prefix)
        widget.configure(state="disabled")

    def _set_ranking_info(self, message: str) -> None:
        self.ranking_requirements_var.set(message)
        if hasattr(self, "ranking_info_text"):
            self.ranking_info_text.configure(state="normal")
            self.ranking_info_text.delete("1.0", "end")
            self.ranking_info_text.insert("1.0", message)
            self.ranking_info_text.configure(state="disabled")

    def _draw_ranked_graph(self, result: RankingResult) -> None:
        canvas = self.ranking_graph
        canvas.delete("all")
        score_map = {
            "Prestiż A": result.raw_prestige,
            "Prestiż A/Nv": result.weighted_prestige,
            "Wektor własny A/Nv": result.eigenvector_prestige,
        }.get(self.ranking_metric_var.get(), result.eigenvector_prestige)
        count = len(result.nodes)
        width = max(1100, count * 65)
        height = max(700, count * 40)
        center_x, center_y = width / 2, height / 2
        radius = min(width, height) * 0.38
        node_radius = max(22, min(34, 900 // max(count, 1)))
        coordinates = {}
        for index, node in enumerate(result.nodes):
            angle = -1.5708 + (2 * 3.141592653589793 * index / count)
            coordinates[node] = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
            )

        graph_edges = [
            (source_index, target_index)
            for source_index in range(count)
            for target_index in range(count)
            if result.adjacency[target_index][source_index]
        ]
        if self.show_ranking_edges_var.get():
            for source_index, target_index in graph_edges[: self.MAX_GRAPH_EDGES]:
                source = result.nodes[source_index]
                target = result.nodes[target_index]
                x1, y1 = coordinates[source]
                x2, y2 = coordinates[target]
                canvas.create_line(
                    x1, y1, x2, y2, fill="#c2cbd3", arrow=tk.LAST, width=1
                )

        ordered_nodes = sorted(
            result.nodes, key=lambda node: score_map[node], reverse=True
        )
        ranks = {node: index + 1 for index, node in enumerate(ordered_nodes)}
        for node in result.nodes:
            x, y = coordinates[node]
            rank = ranks[node]
            fill = "#ffd166" if rank == 1 else ("#d9ecff" if rank <= 5 else "#e5f3e5")
            canvas.create_oval(
                x - node_radius,
                y - node_radius,
                x + node_radius,
                y + node_radius,
                fill=fill,
                outline="#46627c",
                width=2,
            )
            canvas.create_text(
                x,
                y,
                text=f"#{rank}\n{score_map[node]:.3f}",
                font=("TkDefaultFont", 8, "bold"),
            )
        if len(graph_edges) > self.MAX_GRAPH_EDGES and self.show_ranking_edges_var.get():
            canvas.create_text(
                20,
                height - 15,
                text=f"Wyświetlono {self.MAX_GRAPH_EDGES} z {len(graph_edges)} połączeń.",
                anchor="w",
                fill="#6b4f00",
            )
        canvas.configure(scrollregion=(0, 0, width, height))

    def _redraw_current_ranking_graph(self) -> None:
        if self.ranking_result:
            self._draw_ranked_graph(self.ranking_result)

    def _redraw_ranked_graph(self, event: tk.Event) -> None:
        if self.ranking_result and event.widget:
            self._draw_ranked_graph(self.ranking_result)

    def _save_ranking_csv(self) -> None:
        result = self.ranking_result
        if not result:
            messagebox.showinfo("Brak rankingu", "Najpierw oblicz ranking grafu.")
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz ranking do CSV",
            defaultextension=".csv",
            filetypes=(("Pliki CSV", "*.csv"),),
            initialfile="ranking.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file, delimiter=";")
                writer.writerow(
                    ("Rank", "URL", "Incoming links", "Prestige A", "Prestige A/Nv", "Eigenvector")
                )
                ordered_nodes = sorted(
                    result.nodes,
                    key=lambda node: result.eigenvector_prestige[node],
                    reverse=True,
                )
                for rank, node in enumerate(ordered_nodes, start=1):
                    writer.writerow(
                        (
                            rank,
                            node,
                            result.in_degrees[node],
                            result.raw_prestige[node],
                            result.weighted_prestige[node],
                            result.eigenvector_prestige[node],
                        )
                    )
        except OSError as error:
            messagebox.showerror("Nie udało się zapisać CSV", str(error))
            return
        self.status_var.set(f"Zapisano ranking do {path}")

    def _start_crawl(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        raw_url = self.url_var.get().strip()
        url = normalize_url(raw_url, raw_url)
        if not url:
            messagebox.showerror("Nieprawidłowy adres", "Podaj poprawny adres URL z http:// lub https://.")
            return
        try:
            depth = int(self.depth_var.get())
            max_pages = int(self.limit_var.get())
            delay = float(self.delay_var.get())
            if not 0 <= depth <= 10 or not 1 <= max_pages <= 500 or not 0 <= delay <= 10:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Nieprawidłowe ustawienia",
                "Głębokość: 0–10, limit stron: 1–500, opóźnienie: 0–10 sekund.",
            )
            return

        run = CrawlRun(
            name=f"{len(self.runs) + 1}. {urlsplit(url).netloc} — {time.strftime('%H:%M:%S')}",
            start_url=url,
            max_depth=depth,
            max_pages=max_pages,
            strategy=self.strategy_var.get(),
            crawl_mode=self.mode_var.get(),
            using=self.using_var.get(),
        )
        self.active_run = run
        self.stop_event = threading.Event()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.canvas.delete("all")
        self._write_log(f"Start: {url} | głębokość {depth} | limit {max_pages}")
        self.status_var.set("Trwa pobieranie stron…")
        self.worker = threading.Thread(
            target=crawl, args=(run, self.stop_event, self.events, delay), daemon=True
        )
        self.worker.start()

    def _cancel_crawl(self) -> None:
        if self.stop_event:
            self.stop_event.set()
            self.status_var.set("Anulowanie crawl…")

    def _process_events(self) -> None:
        latest_progress: Optional[Tuple[CrawlRun, CrawlProgress]] = None
        final_snapshot: Optional[Tuple[CrawlRun, Dict[str, Page], set[Tuple[str, str]]]] = None
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "page" and isinstance(payload, CrawlProgress) and self.active_run:
                progress = payload
                self._write_log(
                    f"[{progress.page.status}] poziom {progress.page.depth}: "
                    f"{progress.page.title or progress.page.url}"
                )
                latest_progress = (self.active_run, progress)
            elif kind == "log":
                self._write_log(str(payload))
            elif kind == "done" and self.active_run:
                run = self.active_run
                self.runs.append(run)
                self.active_run = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status_var.set(
                    f"Crawl {payload}. Zebrano {len(run.pages)} stron; graf ma {run.graph_depth} poziomów."
                )
                final_snapshot = (run, dict(run.pages), set(run.hyperlinks))
                self._refresh_run_choices()
            self.events.task_done()
        if final_snapshot:
            self.last_crawl_snapshot = final_snapshot
            self._draw_graph(*final_snapshot)
            self._update_metrics(*final_snapshot)
        elif latest_progress:
            run, progress = latest_progress
            snapshot = (run, progress.pages, progress.hyperlinks)
            self.last_crawl_snapshot = snapshot
            self._draw_graph(*snapshot)
            self._update_metrics(*snapshot)
        self.root.after(100, self._process_events)

    def _update_metrics(
        self,
        run: CrawlRun,
        pages: Optional[Dict[str, Page]] = None,
        edges: Optional[set[Tuple[str, str]]] = None,
    ) -> None:
        pages = pages if pages is not None else dict(run.pages)
        edges = edges if edges is not None else set(run.hyperlinks)
        outgoing: Dict[str, int] = {}
        for edge in edges:
            outgoing[edge[0]] = outgoing.get(edge[0], 0) + 1
        root_links = outgoing.get(run.start_url, 0)
        subpage_count = sum(1 for url in pages if url != run.start_url)
        subpage_links = sum(count for url, count in outgoing.items() if url != run.start_url)
        average_subpage_links = subpage_links / subpage_count if subpage_count else 0
        errors = sum(1 for page in pages.values() if page.error)
        self.metrics_var.set(
            f"Strony: {len(pages)} | podstrony: {subpage_count} | "
            f"rzeczywista głębokość: {max((page.depth for page in pages.values()), default=0)}"
            f" / {run.max_depth} | "
            f"linki z głównej: {root_links} | linki z podstron: {subpage_links} "
            f"(średnio {average_subpage_links:.1f}) | linki między stronami: {len(edges)} | "
            f"błędy pobierania: {errors} | strategia: {run.strategy}, tryb: {run.crawl_mode}, "
            f"Using: {run.using}"
        )

    def _draw_graph(
        self,
        run: CrawlRun,
        pages: Optional[Dict[str, Page]] = None,
        edges: Optional[set[Tuple[str, str]]] = None,
    ) -> None:
        self.canvas.delete("all")
        pages = pages if pages is not None else dict(run.pages)
        edges = edges if edges is not None else set(run.hyperlinks)
        by_depth: Dict[int, List[str]] = {}
        for url, page in pages.items():
            by_depth.setdefault(page.depth, []).append(url)
        positions: Dict[str, Tuple[int, int]] = {}
        for depth, urls in by_depth.items():
            for index, url in enumerate(urls):
                positions[url] = (30 + depth * 300, 40 + index * 85)

        visible_edges = sorted(
            (source, target)
            for source, target in edges
            if source in positions and target in positions
        )
        if self.show_crawl_edges_var.get():
            for source, target in visible_edges[: self.MAX_GRAPH_EDGES]:
                x1, y1 = positions[source]
                x2, y2 = positions[target]
                self.canvas.create_line(
                    x1 + 210, y1 + 19, x2, y2 + 19,
                    fill="#c2cbd3", arrow="last", width=1, tags=("edge",)
                )

        for url, page in pages.items():
            x, y = positions[url]
            fill = "#fce8b2" if page.error else ("#d8edff" if page.depth == 0 else "#e5f3e5")
            self.canvas.create_rectangle(
                x, y, x + 210, y + 38, fill=fill, outline="#46627c", tags=("node",)
            )
            label = page.title or urlsplit(url).path or urlsplit(url).netloc
            label = label if len(label) < 31 else label[:28] + "..."
            self.canvas.create_text(
                x + 105, y + 12, text=label, font=("TkDefaultFont", 9, "bold"), tags=("node",)
            )
            address = url if len(url) < 35 else url[:32] + "..."
            self.canvas.create_text(
                x + 105, y + 28, text=address, font=("TkDefaultFont", 8), tags=("node",)
            )

        width = max(900, (max(by_depth.keys(), default=0) + 1) * 300)
        height = max(500, max((len(nodes) for nodes in by_depth.values()), default=1) * 85 + 50)
        for depth in by_depth:
            self.canvas.create_text(
                20 + depth * 300, 18, text=f"Poziom {depth}", anchor="w",
                fill="#334e68", tags=("node",)
            )
        if len(visible_edges) > self.MAX_GRAPH_EDGES and self.show_crawl_edges_var.get():
            self.canvas.create_text(
                20, height - 15,
                text=f"Wyświetlono {self.MAX_GRAPH_EDGES} z {len(visible_edges)} połączeń; "
                "ukryte krawędzie ograniczają czytelność grafu.",
                anchor="w", fill="#6b4f00", tags=("node",)
            )
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _redraw_last_crawl_graph(self) -> None:
        if self.last_crawl_snapshot:
            self._draw_graph(*self.last_crawl_snapshot)

    @staticmethod
    def _enable_canvas_navigation(canvas: tk.Canvas) -> None:
        canvas.configure(cursor="fleur")
        canvas.bind("<ButtonPress-1>", lambda event: canvas.scan_mark(event.x, event.y))
        canvas.bind("<B1-Motion>", lambda event: canvas.scan_dragto(event.x, event.y, gain=1))
        canvas.bind(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"),
        )
        canvas.bind(
            "<Button-4>", lambda event: canvas.yview_scroll(-1 if event.num == 4 else 0, "units")
        )
        canvas.bind(
            "<Button-5>", lambda event: canvas.yview_scroll(1 if event.num == 5 else 0, "units")
        )

    def _refresh_run_choices(self) -> None:
        names = [run.name for run in self.runs]
        self.run_a_combo.configure(values=names)
        self.run_b_combo.configure(values=names)
        self.ranking_run_combo.configure(values=names)
        if names:
            self.ranking_run_var.set(names[-1])
        if len(names) >= 2:
            self.run_a_var.set(names[-2])
            self.run_b_var.set(names[-1])
            self._compare_runs()
        elif names:
            self.run_a_var.set(names[0])

    def _compare_runs(self) -> None:
        run_a = next((run for run in self.runs if run.name == self.run_a_var.get()), None)
        run_b = next((run for run in self.runs if run.name == self.run_b_var.get()), None)
        if not run_a or not run_b:
            self.compare_note.set("Wybierz dwie sesje do porównania.")
            return
        for item in self.compare_tree.get_children():
            self.compare_tree.delete(item)
        values = (
            ("Liczba pobranych stron", len(run_a.pages), len(run_b.pages)),
            ("Głębokość grafu", run_a.graph_depth, run_b.graph_depth),
            ("Liczba krawędzi", len(run_a.edges), len(run_b.edges)),
            ("Linki na stronie głównej",
             sum(1 for edge in run_a.edges if edge[0] == run_a.start_url),
             sum(1 for edge in run_b.edges if edge[0] == run_b.start_url)),
            ("Błędy pobierania", sum(bool(p.error) for p in run_a.pages.values()),
             sum(bool(p.error) for p in run_b.pages.values())),
            ("Strony z tytułem", sum(bool(p.title) for p in run_a.pages.values()),
             sum(bool(p.title) for p in run_b.pages.values())),
        )
        for label, value_a, value_b in values:
            self.compare_tree.insert(
                "", "end", values=(label, value_a, value_b, value_b - value_a)
            )
        only_a = len(set(run_a.pages) - set(run_b.pages))
        only_b = len(set(run_b.pages) - set(run_a.pages))
        self.compare_note.set(
            f"A: {run_a.strategy}, {run_a.crawl_mode}, {run_a.using}; "
            f"B: {run_b.strategy}, {run_b.crawl_mode}, {run_b.using}. "
            f"Tylko w A: {only_a} adresów; tylko w B: {only_b}. "
            "Tryb server ogranicza crawl do tej samej domeny, web dopuszcza inne domeny. "
            "Breadth first najpierw bada bliższe poziomy; Depth first schodzi w głąb jednej gałęzi. "
            "all links może odkryć więcej zasobów niż images+hyperlinks."
        )

    def _save_csv(self) -> None:
        run = self.active_run
        if run is None:
            run = next((item for item in self.runs if item.name == self.run_b_var.get()), None)
        if not run:
            messagebox.showinfo("Brak danych", "Najpierw wykonaj crawl.")
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz dane crawl",
            defaultextension=".csv",
            filetypes=(("Pliki CSV", "*.csv"),),
            initialfile="crawl.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file, delimiter=";")
                writer.writerow(("URL", "Keyword", "Title", "Description", "Body", "Depth", "Status"))
                for page in run.pages.values():
                    writer.writerow(
                        (page.url, page.keywords, page.title, page.description, page.body, page.depth, page.status)
                    )
        except OSError as error:
            messagebox.showerror("Nie udało się zapisać CSV", str(error))
            return
        self.status_var.set(f"Zapisano dane do {path}")

    def _write_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
