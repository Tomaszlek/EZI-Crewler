"""Application entry point."""

import tkinter as tk

from ezi_crewler.gui import CrawlerApp


def main() -> None:
    root = tk.Tk()
    CrawlerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
