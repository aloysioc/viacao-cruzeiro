from pathlib import Path
import subprocess
import win32com.client

src = Path(r"E:\repos\viacao-cruzeiro\docs\questionario-dados-e-ingestao-producao.docx")
out_dir = Path(r"C:\Users\aloys\AppData\Local\Temp\vcruzeiro-questionario-render")
out_dir.mkdir(parents=True, exist_ok=True)
pdf = out_dir / "questionario-dados-e-ingestao-producao.pdf"

word = win32com.client.DispatchEx("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
try:
    document = word.Documents.Open(str(src), ReadOnly=True)
    document.ExportAsFixedFormat(str(pdf), 17)
    document.Close(False)
finally:
    word.Quit()

subprocess.run([
    r"C:\Users\aloys\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe",
    "-png", "-r", "160", str(pdf), str(out_dir / "page")
], check=True)
for item in sorted(out_dir.glob("page-*.png")):
    print(item)
