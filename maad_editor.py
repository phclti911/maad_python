import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser, font
import ctypes

# Extras opcionais:
# pip install reportlab pyttsx3
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    import pyttsx3
    TTS_OK = True
except Exception:
    TTS_OK = False


def resource_path(relative_path: str) -> str:
    """
    Resolve caminho corretamente:
    - PyInstaller: sys._MEIPASS
    - Normal: pasta onde está o arquivo .py (via __file__)
    """
    if getattr(sys, "_MEIPASS", None):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def register_font_windows(font_path: str) -> bool:
    """
    Registra fonte (TTF/OTF) no Windows para a sessão atual (não instala no sistema)
    e dispara WM_FONTCHANGE para o Tk reconhecer a mudança.
    """
    try:
        FR_PRIVATE = 0x10
        path = os.path.abspath(font_path)

        add_font = ctypes.windll.gdi32.AddFontResourceExW
        res = add_font(path, FR_PRIVATE, 0)

        HWND_BROADCAST = 0xFFFF
        WM_FONTCHANGE = 0x001D
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)

        return res > 0
    except Exception as e:
        print("register_font_windows erro:", e)
        return False


class MAADLikeEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MAAD Editor (Python)")
        self.geometry("1150x740")
        self.minsize(900, 600)

        self.current_file = None
        self.text_modified = False

        # Estado visual
        self.var_font_family = tk.StringVar(value="Arial")
        self.var_font_size = tk.IntVar(value=14)
        self.var_fg = tk.StringVar(value="#111111")
        self.var_bg = tk.StringVar(value="#ffffff")
        self.var_wrap = tk.BooleanVar(value=True)
        self.var_line_spacing = tk.DoubleVar(value=1.2)
        self.var_zoom = tk.IntVar(value=100)

        # Preset dislexia
        self.dyslexia_mode_on = False
        self._normal_snapshot = None

        # Pasta de fontes
        self.fonts_dir = resource_path(os.path.join("assets", "fonts"))

        # -------- TTS state --------
        self.tts_engine = None
        self.tts_thread = None
        self.tts_lock = threading.Lock()

        self.tts_active = False
        self.tts_paused = False

        self.tts_text = ""
        self.tts_sentences = []
        self.tts_idx = 0

        self.var_tts_rate = tk.IntVar(value=175)
        self.var_tts_voice = tk.StringVar(value="(padrão)")

        # UI
        self._build_ui()
        self._bind_shortcuts()

        # Fonts
        self.opendyslexic_loaded = self.load_fonts_from_assets(show_popup=False)

        # TTS
        self._init_tts_if_possible()
        self._apply_style()
        self._update_tts_buttons()

    # ---------------- Fonts ----------------
    def load_fonts_from_assets(self, show_popup: bool = True) -> bool:
        os.makedirs(self.fonts_dir, exist_ok=True)

        try:
            files = os.listdir(self.fonts_dir)
        except Exception:
            files = []

        font_files = [
            os.path.join(self.fonts_dir, f)
            for f in files
            if (f.lower().endswith(".ttf") or f.lower().endswith(".otf"))
            and "opendyslexic" in f.lower()
        ]

        ok_any = False
        if sys.platform.startswith("win") and font_files:
            for p in font_files:
                ok_any = register_font_windows(p) or ok_any

        try:
            self.update_idletasks()
        except Exception:
            pass

        self._refresh_font_list()
        od = self._pick_opendyslexic_family()

        if show_popup:
            msg = (
                f"Pasta de fontes:\n{self.fonts_dir}\n\n"
                f"Arquivos encontrados ({len(files)}):\n"
                + ("\n".join(files) if files else "(vazio)")
                + "\n\n"
                f"Fontes OpenDyslexic (TTF/OTF) encontradas ({len(font_files)}):\n"
                + ("\n".join([os.path.basename(x) for x in font_files]) if font_files else "(nenhuma)")
                + "\n\n"
                f"OpenDyslexic detectada no Tk? {'SIM' if od else 'NÃO'}\n"
                f"Registro no Windows? {'OK' if ok_any else 'NÃO/NA'}"
            )
            messagebox.showinfo("Recarregar fontes", msg)

        return bool(od) or ok_any

    def _refresh_font_list(self):
        try:
            self.font_combo["values"] = sorted(font.families())
        except Exception:
            pass

    def _pick_opendyslexic_family(self):
        fams = font.families()
        for key in ["OpenDyslexic", "Open Dyslexic", "OpenDyslexic3"]:
            matches = [f for f in fams if key.lower() in f.lower()]
            if matches:
                return matches[0]
        return None

    # ---------------- TTS ----------------
    def _init_tts_if_possible(self):
        if not TTS_OK:
            self.tts_engine = None
            return
        try:
            self.tts_engine = pyttsx3.init()
            voices = self.tts_engine.getProperty("voices") or []
            voice_names = ["(padrão)"]
            for v in voices:
                name = getattr(v, "name", None) or getattr(v, "id", "voz")
                voice_names.append(str(name))
            self.voice_combo["values"] = voice_names
            self.var_tts_voice.set("(padrão)")
            self.tts_engine.setProperty("rate", int(self.var_tts_rate.get()))
        except Exception as e:
            self.tts_engine = None
            print("Falha ao iniciar TTS:", e)

    def _apply_tts_settings(self):
        if not self.tts_engine:
            return
        try:
            self.tts_engine.setProperty("rate", int(self.var_tts_rate.get()))
            if self.var_tts_voice.get() != "(padrão)":
                target_name = self.var_tts_voice.get()
                voices = self.tts_engine.getProperty("voices") or []
                for v in voices:
                    name = getattr(v, "name", None) or getattr(v, "id", "")
                    if str(name) == target_name:
                        self.tts_engine.setProperty("voice", v.id)
                        break
        except Exception as e:
            print("Erro ao aplicar config TTS:", e)

    def _split_sentences(self, text: str):
        seps = [".", "!", "?", "\n", ";", ":"]
        out = []
        buf = []
        for ch in text:
            buf.append(ch)
            if ch in seps:
                s = "".join(buf).strip()
                if s:
                    out.append(s)
                buf = []
        rest = "".join(buf).strip()
        if rest:
            out.append(rest)
        return [s for s in out if s.strip()]

    def _start_tts_thread(self):
        self._update_tts_buttons()
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

    def _tts_worker(self):
        """
        TTS estável:
        - Divide em frases
        - Fala 1 frase por vez
        - Mantém índice (self.tts_idx) para retomar corretamente
        """
        if not self.tts_engine:
            return

        try:
            self._apply_tts_settings()

            with self.tts_lock:
                # gera lista só uma vez, e mantém idx para retomar
                if not self.tts_sentences:
                    self.tts_sentences = self._split_sentences(self.tts_text.strip())
                if self.tts_idx < 0:
                    self.tts_idx = 0

            while True:
                with self.tts_lock:
                    if not self.tts_active:
                        return
                    paused = self.tts_paused
                    idx = self.tts_idx
                    sentences = self.tts_sentences

                if paused:
                    threading.Event().wait(0.08)
                    continue

                if idx >= len(sentences):
                    break

                sentence = sentences[idx]

                # falar 1 frase por vez (não “morre” na primeira)
                self.tts_engine.say(sentence)
                self.tts_engine.runAndWait()

                with self.tts_lock:
                    self.tts_idx += 1

        except Exception as e:
            print("TTS erro:", e)
        finally:
            with self.tts_lock:
                self.tts_active = False
                self.tts_paused = False
            self.after(0, self._update_tts_buttons)
            self.after(0, lambda: self.status.config(text="TTS: pronto."))

    def tts_speak_all(self):
        if not self.tts_engine:
            messagebox.showwarning("TTS", "TTS não está disponível. Instale: pip install pyttsx3")
            return

        text_value = self.text.get("1.0", tk.END).strip()
        if not text_value:
            messagebox.showinfo("TTS", "Não há texto para ler.")
            return

        self.tts_stop()
        with self.tts_lock:
            self.tts_text = text_value
            self.tts_sentences = []
            self.tts_idx = 0
            self.tts_active = True
            self.tts_paused = False

        self.status.config(text="TTS: lendo texto completo…")
        self._start_tts_thread()

    def tts_speak_selection(self):
        if not self.tts_engine:
            messagebox.showwarning("TTS", "TTS não está disponível. Instale: pip install pyttsx3")
            return

        try:
            sel = self.text.get("sel.first", "sel.last").strip()
        except tk.TclError:
            sel = ""

        if not sel:
            messagebox.showinfo("TTS", "Selecione um trecho para ler.")
            return

        self.tts_stop()
        with self.tts_lock:
            self.tts_text = sel
            self.tts_sentences = []
            self.tts_idx = 0
            self.tts_active = True
            self.tts_paused = False

        self.status.config(text="TTS: lendo seleção…")
        self._start_tts_thread()

    def tts_pause(self):
        with self.tts_lock:
            if not self.tts_active:
                return
            self.tts_paused = True
        try:
            self.tts_engine.stop()
        except Exception:
            pass
        self.status.config(text="TTS: pausado.")
        self._update_tts_buttons()

    def tts_resume(self):
        with self.tts_lock:
            if not self.tts_active:
                return
            self.tts_paused = False
        self.status.config(text="TTS: retomando…")
        self._update_tts_buttons()

    def tts_stop(self):
        with self.tts_lock:
            self.tts_active = False
            self.tts_paused = False
            self.tts_idx = 0
            self.tts_sentences = []
            self.tts_text = ""
        try:
            if self.tts_engine:
                self.tts_engine.stop()
        except Exception:
            pass
        self.status.config(text="TTS: parado.")
        self._update_tts_buttons()

    def _update_tts_buttons(self):
        if not self.tts_engine:
            for b in [self.btn_tts_all, self.btn_tts_sel, self.btn_tts_pause, self.btn_tts_resume, self.btn_tts_stop]:
                b.configure(state="disabled")
            self.rate_spin.configure(state="disabled")
            self.voice_combo.configure(state="disabled")
            return

        with self.tts_lock:
            active = self.tts_active
            paused = self.tts_paused

        self.btn_tts_all.configure(state=("disabled" if active and not paused else "normal"))
        self.btn_tts_sel.configure(state=("disabled" if active and not paused else "normal"))
        self.btn_tts_pause.configure(state=("normal" if active and not paused else "disabled"))
        self.btn_tts_resume.configure(state=("normal" if active and paused else "disabled"))
        self.btn_tts_stop.configure(state=("normal" if active else "disabled"))

        self.rate_spin.configure(state=("disabled" if active and not paused else "normal"))
        self.voice_combo.configure(state=("disabled" if active and not paused else "readonly"))

    # ---------------- UI ----------------
    def _build_ui(self):
        self._build_menu()

        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Novo", command=self.new_file).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Abrir", command=self.open_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Salvar", command=self.save_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Salvar como", command=self.save_file_as).pack(side=tk.LEFT, padx=6)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(toolbar, text="Fonte:").pack(side=tk.LEFT)
        self.font_combo = ttk.Combobox(
            toolbar, textvariable=self.var_font_family,
            values=sorted(font.families()), width=20, state="readonly"
        )
        self.font_combo.pack(side=tk.LEFT, padx=(6, 10))
        self.font_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_style())

        ttk.Label(toolbar, text="Tam:").pack(side=tk.LEFT)
        ttk.Spinbox(toolbar, from_=8, to=72, textvariable=self.var_font_size, width=5, command=self._apply_style)\
            .pack(side=tk.LEFT, padx=(6, 10))

        ttk.Button(toolbar, text="B", command=self.toggle_bold).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="I", command=self.toggle_italic).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="U", command=self.toggle_underline).pack(side=tk.LEFT, padx=4)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(toolbar, text="Cor texto", command=self.pick_fg).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Cor fundo", command=self.pick_bg).pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Modo Dislexia", command=self.toggle_dyslexia_mode).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Recarregar fontes", command=lambda: self.load_fonts_from_assets(show_popup=True))\
            .pack(side=tk.LEFT, padx=6)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(toolbar, text="Espaço:").pack(side=tk.LEFT)
        ttk.Spinbox(toolbar, from_=1.0, to=2.5, increment=0.1,
                    textvariable=self.var_line_spacing, width=5, command=self._apply_style)\
            .pack(side=tk.LEFT, padx=(6, 10))

        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT)
        ttk.Spinbox(toolbar, from_=50, to=200, increment=10,
                    textvariable=self.var_zoom, width=5, command=self._apply_style)\
            .pack(side=tk.LEFT, padx=(6, 10))

        ttk.Checkbutton(toolbar, text="Quebra linha", variable=self.var_wrap, command=self._apply_style)\
            .pack(side=tk.LEFT, padx=6)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # -------- TTS controls --------
        ttsbar = ttk.Frame(toolbar)
        ttsbar.pack(side=tk.LEFT, padx=4)

        self.btn_tts_all = ttk.Button(ttsbar, text="Ler tudo", command=self.tts_speak_all)
        self.btn_tts_all.grid(row=0, column=0, padx=2)

        self.btn_tts_sel = ttk.Button(ttsbar, text="Ler seleção", command=self.tts_speak_selection)
        self.btn_tts_sel.grid(row=0, column=1, padx=2)

        self.btn_tts_pause = ttk.Button(ttsbar, text="Pausar", command=self.tts_pause)
        self.btn_tts_pause.grid(row=0, column=2, padx=2)

        self.btn_tts_resume = ttk.Button(ttsbar, text="Retomar", command=self.tts_resume)
        self.btn_tts_resume.grid(row=0, column=3, padx=2)

        self.btn_tts_stop = ttk.Button(ttsbar, text="Parar", command=self.tts_stop)
        self.btn_tts_stop.grid(row=0, column=4, padx=2)

        ttk.Label(ttsbar, text="Vel:").grid(row=0, column=5, padx=(10, 2))
        self.rate_spin = ttk.Spinbox(
            ttsbar, from_=90, to=280, increment=5,
            textvariable=self.var_tts_rate, width=5,
            command=self._on_tts_settings_changed
        )
        self.rate_spin.grid(row=0, column=6, padx=2)

        ttk.Label(ttsbar, text="Voz:").grid(row=0, column=7, padx=(10, 2))
        self.voice_combo = ttk.Combobox(
            ttsbar, textvariable=self.var_tts_voice,
            values=["(padrão)"], width=18, state="readonly"
        )
        self.voice_combo.grid(row=0, column=8, padx=2)
        self.voice_combo.bind("<<ComboboxSelected>>", lambda e: self._on_tts_settings_changed())

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(toolbar, text="Exportar PDF", command=self.export_pdf).pack(side=tk.LEFT, padx=4)

        # Editor
        main = ttk.Frame(self)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.text = tk.Text(
            main, wrap="word", undo=True,
            padx=14, pady=12, borderwidth=0, highlightthickness=0
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(main, orient=tk.VERTICAL, command=self.text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scroll.set)

        self.status = ttk.Label(self, text="Pronto.", anchor="w", padding=(10, 6))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        self.text.tag_configure("bold")
        self.text.tag_configure("italic")
        self.text.tag_configure("underline")

        self.text.bind("<<Modified>>", self._on_modified)

    def _on_tts_settings_changed(self):
        with self.tts_lock:
            active = self.tts_active and not self.tts_paused
        if active:
            return
        self._apply_tts_settings()

    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        m_file = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Arquivo", menu=m_file)
        m_file.add_command(label="Novo", accelerator="Ctrl+N", command=self.new_file)
        m_file.add_command(label="Abrir...", accelerator="Ctrl+O", command=self.open_file)
        m_file.add_command(label="Salvar", accelerator="Ctrl+S", command=self.save_file)
        m_file.add_command(label="Salvar como", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        m_file.add_separator()
        m_file.add_command(label="Exportar PDF...", command=self.export_pdf)
        m_file.add_separator()
        m_file.add_command(label="Sair", command=self.on_exit)

        m_acc = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Acessibilidade", menu=m_acc)
        m_acc.add_command(label="Alternar Modo Dislexia", command=self.toggle_dyslexia_mode)
        m_acc.add_command(label="Recarregar fontes", command=lambda: self.load_fonts_from_assets(show_popup=True))

        m_tts = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Leitura (TTS)", menu=m_tts)
        m_tts.add_command(label="Ler tudo", command=self.tts_speak_all)
        m_tts.add_command(label="Ler seleção", command=self.tts_speak_selection)
        m_tts.add_separator()
        m_tts.add_command(label="Pausar", command=self.tts_pause)
        m_tts.add_command(label="Retomar", command=self.tts_resume)
        m_tts.add_command(label="Parar", command=self.tts_stop)

        m_help = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Ajuda", menu=m_help)
        m_help.add_command(label="Sobre (debug)", command=self.show_about)

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.new_file())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-Shift-S>", lambda e: self.save_file_as())

        self.bind("<F5>", lambda e: self.tts_speak_all())
        self.bind("<F6>", lambda e: self.tts_speak_selection())
        self.bind("<F7>", lambda e: self.tts_pause())
        self.bind("<F8>", lambda e: self.tts_resume())
        self.bind("<F9>", lambda e: self.tts_stop())

        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ---------------- Editor behaviors ----------------
    def _on_modified(self, event=None):
        if self.text.edit_modified():
            self.text_modified = True
            self.status.config(text="Editando… (não salvo)")
            self.text.edit_modified(False)

    def _apply_style(self):
        base_size = int(self.var_font_size.get())
        zoom = int(self.var_zoom.get())
        size = max(6, int(base_size * (zoom / 100)))

        family = self.var_font_family.get()
        fg = self.var_fg.get()
        bg = self.var_bg.get()

        self.text.configure(
            font=(family, size),
            fg=fg,
            bg=bg,
            insertbackground=fg,
            selectbackground="#9ecbff" if bg.lower() in ["#ffffff", "#faf7f0"] else "#444444",
            wrap="word" if self.var_wrap.get() else "none",
            spacing1=int(size * (self.var_line_spacing.get() - 1.0) * 0.6),
            spacing3=int(size * (self.var_line_spacing.get() - 1.0) * 0.6),
        )

        self.text.tag_configure("bold", font=(family, size, "bold"))
        self.text.tag_configure("italic", font=(family, size, "italic"))
        self.text.tag_configure("underline", font=(family, size, "underline"))

        self.status.config(text=f"Fonte: {family} | {size}px | Espaço {self.var_line_spacing.get():.1f} | Zoom {zoom}%")

    def toggle_dyslexia_mode(self):
        if not self.dyslexia_mode_on:
            self._normal_snapshot = {
                "font": self.var_font_family.get(),
                "size": int(self.var_font_size.get()),
                "fg": self.var_fg.get(),
                "bg": self.var_bg.get(),
                "wrap": bool(self.var_wrap.get()),
                "spacing": float(self.var_line_spacing.get()),
                "zoom": int(self.var_zoom.get()),
            }

            od = self._pick_opendyslexic_family()
            if not od:
                self.load_fonts_from_assets(show_popup=False)
                od = self._pick_opendyslexic_family()

            if od:
                self.var_font_family.set(od)

            self.var_font_size.set(max(16, int(self.var_font_size.get())))
            self.var_line_spacing.set(1.6)
            self.var_bg.set("#FAF7F0")
            self.var_fg.set("#111111")
            self.var_wrap.set(True)
            self.var_zoom.set(max(115, int(self.var_zoom.get())))

            self.dyslexia_mode_on = True
            self._apply_style()
            self.status.config(text="Modo Dislexia: ATIVADO")
        else:
            if self._normal_snapshot:
                self.var_font_family.set(self._normal_snapshot["font"])
                self.var_font_size.set(self._normal_snapshot["size"])
                self.var_fg.set(self._normal_snapshot["fg"])
                self.var_bg.set(self._normal_snapshot["bg"])
                self.var_wrap.set(self._normal_snapshot["wrap"])
                self.var_line_spacing.set(self._normal_snapshot["spacing"])
                self.var_zoom.set(self._normal_snapshot["zoom"])

            self.dyslexia_mode_on = False
            self._apply_style()
            self.status.config(text="Modo Dislexia: DESATIVADO")

    def _toggle_tag_on_selection(self, tag):
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
        except tk.TclError:
            messagebox.showinfo("Seleção", "Selecione um trecho primeiro.")
            return

        if self.text.tag_nextrange(tag, start, end):
            self.text.tag_remove(tag, start, end)
        else:
            self.text.tag_add(tag, start, end)

    def toggle_bold(self):
        self._toggle_tag_on_selection("bold")

    def toggle_italic(self):
        self._toggle_tag_on_selection("italic")

    def toggle_underline(self):
        self._toggle_tag_on_selection("underline")

    def pick_fg(self):
        c = colorchooser.askcolor(title="Escolha a cor do texto")
        if c and c[1]:
            self.var_fg.set(c[1])
            self._apply_style()

    def pick_bg(self):
        c = colorchooser.askcolor(title="Escolha a cor do fundo")
        if c and c[1]:
            self.var_bg.set(c[1])
            self._apply_style()

    # ---------------- Files ----------------
    def _confirm_save_if_modified(self):
        if not self.text_modified:
            return True
        ans = messagebox.askyesnocancel("Alterações", "Você tem alterações não salvas. Deseja salvar agora?")
        if ans is None:
            return False
        if ans is True:
            return self.save_file()
        return True

    def new_file(self):
        if not self._confirm_save_if_modified():
            return
        self.text.delete("1.0", tk.END)
        self.current_file = None
        self.text_modified = False
        self.title("MAAD Editor (Python) - Novo arquivo")
        self.status.config(text="Novo arquivo.")

    def open_file(self):
        if not self._confirm_save_if_modified():
            return

        path = filedialog.askopenfilename(
            title="Abrir arquivo",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", content)
            self.current_file = path
            self.text_modified = False
            self.title(f"MAAD Editor (Python) - {os.path.basename(path)}")
            self.status.config(text=f"Aberto: {path}")
        except Exception as e:
            messagebox.showerror("Erro ao abrir", str(e))

    def save_file(self):
        if self.current_file is None:
            return self.save_file_as()
        try:
            content = self.text.get("1.0", tk.END)
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(content.rstrip("\n"))
            self.text_modified = False
            self.status.config(text=f"Salvo: {self.current_file}")
            return True
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return False

    def save_file_as(self):
        path = filedialog.asksaveasfilename(
            title="Salvar como",
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt")]
        )
        if not path:
            return False
        self.current_file = path
        ok = self.save_file()
        if ok:
            self.title(f"MAAD Editor (Python) - {os.path.basename(path)}")
        return ok

    def export_pdf(self):
        if not REPORTLAB_OK:
            messagebox.showwarning("PDF", "Instale: pip install reportlab")
            return

        path = filedialog.asksaveasfilename(
            title="Exportar PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        if not path:
            return

        text_value = self.text.get("1.0", tk.END).rstrip("\n")
        try:
            c = canvas.Canvas(path, pagesize=A4)
            width, height = A4
            margin = 50
            y = height - margin
            c.setFont("Helvetica", 12)

            max_width = width - 2 * margin

            def draw_line(line, y_pos):
                c.drawString(margin, y_pos, line)

            for raw_line in text_value.splitlines():
                line = raw_line
                while True:
                    if c.stringWidth(line, "Helvetica", 12) <= max_width:
                        if y < margin:
                            c.showPage()
                            c.setFont("Helvetica", 12)
                            y = height - margin
                        draw_line(line, y)
                        y -= 16
                        break

                    cut = max(20, int(len(line) * 0.7))
                    while cut < len(line) and c.stringWidth(line[:cut], "Helvetica", 12) < max_width:
                        cut += 1
                    cut = max(1, cut - 1)
                    chunk = line[:cut]

                    if " " in chunk:
                        cut2 = chunk.rfind(" ")
                        if cut2 > 10:
                            chunk = line[:cut2]
                            line = line[cut2 + 1:]
                        else:
                            line = line[cut:]
                    else:
                        line = line[cut:]

                    if y < margin:
                        c.showPage()
                        c.setFont("Helvetica", 12)
                        y = height - margin
                    draw_line(chunk, y)
                    y -= 16

            c.save()
            self.status.config(text=f"PDF exportado: {path}")
            messagebox.showinfo("PDF", "PDF exportado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro ao exportar PDF", str(e))

    # ---------------- About / Exit ----------------
    def show_about(self):
        od = self._pick_opendyslexic_family()
        files = []
        try:
            files = os.listdir(self.fonts_dir) if os.path.isdir(self.fonts_dir) else []
        except Exception:
            files = []

        msg = (
            "MAAD Editor (Python)\n"
            "Feito e idealizado por Pedro Henrique Crispim Lacerda, como TCC 2025.2 de Sistemas de Informação do Centro Universitário Paraíso - UniFAP - Ceará - Brasil\n\n"
            "DEBUG\n\n"
            f"Plataforma: {sys.platform}\n"
            f"Pasta assets/fonts:\n{self.fonts_dir}\n"
            f"Existe? {'SIM' if os.path.isdir(self.fonts_dir) else 'NÃO'}\n\n"
            f"Arquivos na pasta ({len(files)}):\n"
            + ("\n".join(files) if files else "(vazio)")
            + "\n\n"
            f"OpenDyslexic detectada no Tk? {'SIM' if od else 'NÃO'}\n"
            f"PDF: {'OK' if REPORTLAB_OK else 'NÃO'} | TTS: {'OK' if bool(self.tts_engine) else 'NÃO'}\n\n"
            "Atalhos TTS: F5 lê tudo | F6 lê seleção | F7 pausa | F8 retoma | F9 para"
        )
        messagebox.showinfo("Sobre (debug)", msg)

    def on_exit(self):
        self.tts_stop()
        if not self._confirm_save_if_modified():
            return
        self.destroy()


if __name__ == "__main__":
    app = MAADLikeEditor()
    app.mainloop()
