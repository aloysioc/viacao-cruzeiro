$src = 'E:\repos\viacao-cruzeiro\docs\questionario-dados-e-ingestao-producao.docx'
$outDir = 'C:\Users\aloys\AppData\Local\Temp\vcruzeiro-questionario-render'
$pdf = Join-Path $outDir 'questionario-dados-e-ingestao-producao.pdf'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $document = $word.Documents.Open($src, $false, $true)
  $document.ExportAsFixedFormat($pdf, 17)
  $document.Close($false)
}
finally {
  $word.Quit()
}
& 'C:\Users\aloys\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe' -png -r 160 $pdf (Join-Path $outDir 'page')
Get-ChildItem $outDir -Filter 'page-*.png' | Sort-Object Name | Select-Object -ExpandProperty FullName
