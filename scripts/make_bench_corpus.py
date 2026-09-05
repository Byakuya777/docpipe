"""Generate the 10-document benchmark corpus (PROJECT_SPEC.md §12).

`data/` is gitignored, so the corpus itself is not in the repo — this script is,
so the benchmark can be reproduced from a clean checkout.

The PDFs are built by hand rather than with a library: a benchmark that needs a
PDF-authoring dependency to reproduce is a worse benchmark, and the documents
only need to be small, valid, and textually distinct. Keeping them uniform in
size matters more than realism here — ten documents of wildly different lengths
would measure the corpus, not the architecture.

    python scripts/make_bench_corpus.py [outdir]
"""

import sys
from pathlib import Path

PAPERS = [
    ("Sparse Attention for Long Documents",
     "Rivera, Okonkwo, Lindqvist",
     "We study sparse attention for document-length inputs and report a 3x",
     "reduction in memory with no measurable loss in retrieval accuracy."),
    ("Contrastive Pretraining for Tabular Data",
     "Haddad, Nakamura, Ferreira",
     "We adapt contrastive objectives to heterogeneous tabular schemas and",
     "evaluate transfer across twelve public benchmark datasets."),
    ("A Survey of Retrieval-Augmented Generation",
     "Kowalski, Adeyemi, Sorensen",
     "We survey retrieval-augmented generation systems published since 2020",
     "and propose a taxonomy organised by index granularity."),
    ("Robust Calibration Under Distribution Shift",
     "Petrov, Almeida, Whitfield",
     "We show that temperature scaling degrades sharply under covariate shift",
     "and introduce a shift-aware recalibration procedure."),
    ("Efficient Fine-Tuning with Low-Rank Adapters",
     "Duarte, Ivanova, Mensah",
     "We compare low-rank adaptation against full fine-tuning across seven",
     "downstream tasks at matched parameter budgets."),
    ("Graph Neural Networks for Citation Prediction",
     "Bergstrom, Chaudhary, Oyelaran",
     "We model citation dynamics as a temporal graph and predict future edges",
     "using a message-passing architecture with decay-weighted aggregation."),
    ("Adversarial Robustness of Document Classifiers",
     "Novak, Tanaka, Bouchard",
     "We construct character-level perturbations that defeat document",
     "classifiers while preserving human readability."),
    ("Streaming Summarisation of Technical Reports",
     "Silva, Andersson, Rahimi",
     "We present a streaming summariser that emits partial summaries under a",
     "fixed latency budget and refines them as more text arrives."),
    ("Measuring Annotation Noise in Legal Corpora",
     "Costa, Virtanen, Mbeki",
     "We quantify inter-annotator disagreement across three legal corpora and",
     "estimate its effect on downstream classifier accuracy."),
    ("Cross-Lingual Transfer for Low-Resource Extraction",
     "Jarvis, Delacroix, Nwankwo",
     "We evaluate zero-shot cross-lingual transfer for entity extraction in",
     "nine low-resource languages using a shared subword vocabulary."),
]


def _escape(text: str) -> str:
    """Escape the three characters that are syntax inside a PDF string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(title: str, authors: str, *abstract_lines: str) -> bytes:
    lines = [title, authors, "Abstract."] + list(abstract_lines)
    text_ops = f"BT /F1 14 Tf 72 720 Td ({_escape(lines[0])}) Tj\n"
    for line in lines[1:]:
        text_ops += f"0 -22 Td ({_escape(line)}) Tj\n"
    text_ops += "ET"
    stream = text_ops.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def main() -> None:
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/bench")
    outdir.mkdir(parents=True, exist_ok=True)
    for n, paper in enumerate(PAPERS, start=1):
        path = outdir / f"paper{n:02d}.pdf"
        path.write_bytes(build_pdf(*paper))
        print(f"  {path}  {path.stat().st_size} bytes")
    print(f"\n{len(PAPERS)} documents in {outdir}")


if __name__ == "__main__":
    main()
