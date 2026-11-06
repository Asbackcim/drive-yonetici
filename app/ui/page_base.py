from __future__ import annotations

import customtkinter as ctk

from . import theme
from .context import AppContext
from .widgets import TaskRunner


class Page(ctk.CTkFrame):
    title = ""

    def __init__(self, master, ctx: AppContext, runner: TaskRunner):
        super().__init__(master, fg_color=theme.BG, corner_radius=0)
        self.ctx = ctx
        self.runner = runner
        self.status = None

    def on_show(self) -> None:
        """Sayfa görünür olduğunda çağrılır."""

    def on_account_changed(self) -> None:
        """Seçili hesap değiştiğinde çağrılır."""

    def set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.configure(text=text)

    def status_label(self, master) -> ctk.CTkLabel:
        self.status = ctk.CTkLabel(master, text="", font=theme.font(12), text_color=theme.MUTED, anchor="w")
        return self.status
