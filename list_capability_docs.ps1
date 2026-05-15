Write-Host ""
Write-Host "=== GovRisk Capability Library ===" -ForegroundColor Cyan
Write-Host ""

$path = ".\capability_library"
$files = Get-ChildItem -Path $path -File | Sort-Object Name

Write-Host "Total documents: $($files.Count)" -ForegroundColor Green
Write-Host ""

$i = 1
foreach ($file in $files) {
    $size = [math]::Round($file.Length / 1KB, 1)
    Write-Host "$i. $($file.Name) ($size KB)" -ForegroundColor White
    $i++
}
