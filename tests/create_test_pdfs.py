"""
create_test_pdfs.py

Creates 3 sample PDFs in data/uploads/ for testing the extraction pipeline.
Run once from the backend/ directory:

    .venv\\Scripts\\python.exe ..\tests\create_test_pdfs.py
"""

import sys
from pathlib import Path

import fitz  # PyMuPDF

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "uploads"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def make_pdf(filename: str, pages: list[dict]):
    """Create a simple PDF with given pages."""
    doc = fitz.open()
    for page_data in pages:
        page = doc.new_page()
        page.insert_text(
            point=(50, 100),
            text=page_data["text"],
            fontsize=12,
        )
    out_path = OUTPUT_DIR / filename
    doc.save(str(out_path))
    doc.close()
    print(f"Created: {out_path}")


if __name__ == "__main__":
    # PDF 1 — Operating Systems notes
    make_pdf("OS_Lecture_1.pdf", [
        {"text": "Chapter 1: Introduction to Operating Systems\n\nAn operating system is software that manages computer hardware and software resources."},
        {"text": "Chapter 1 continued: Process Management\n\nA process is a program in execution. The OS is responsible for process creation and deletion."},
        {"text": "Chapter 1 continued: Memory Management\n\nThe OS manages the allocation of memory space to processes as needed."},
    ])

    # PDF 2 — DBMS notes
    make_pdf("DBMS_Lecture_1.pdf", [
        {"text": "Chapter 1: Introduction to DBMS\n\nA Database Management System is software that interacts with the user, applications, and the database itself."},
        {"text": "Chapter 1 continued: Normalization\n\nNormalization is the process of organizing data to reduce redundancy and improve data integrity."},
    ])

    # PDF 3 — Scheduling algorithms
    make_pdf("OS_Scheduling.pdf", [
        {"text": "CPU Scheduling Algorithms\n\nFCFS: First Come First Served. Processes are scheduled in the order they arrive."},
        {"text": "Round Robin Scheduling\n\nEach process gets a fixed time quantum. After the quantum expires, the process is preempted."},
        {"text": "SJF: Shortest Job First\n\nThe process with the smallest next CPU burst is scheduled first."},
        {"text": "Priority Scheduling\n\nEach process is assigned a priority. The CPU is allocated to the process with the highest priority."},
    ])

    print("\nAll 3 test PDFs created successfully in data/uploads/")
