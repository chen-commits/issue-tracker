param(
  [Parameter(Mandatory=$true)][string]$InputDeck,
  [Parameter(Mandatory=$true)][string]$PreviewDirectory
)
$ErrorActionPreference = 'Stop'
$deckPath = (Resolve-Path -LiteralPath $InputDeck).Path
New-Item -ItemType Directory -Path $PreviewDirectory -Force | Out-Null
$previewPath = (Resolve-Path -LiteralPath $PreviewDirectory).Path
$powerPoint = New-Object -ComObject PowerPoint.Application
$initialPresentationCount = $powerPoint.Presentations.Count
$deck = $null
try {
  $deck = $powerPoint.Presentations.Open($deckPath, -1, 0, 0)
  for ($slideIndex=1; $slideIndex -le $deck.Slides.Count; $slideIndex++) {
    $slide = $deck.Slides.Item($slideIndex)
    $targetFile = Join-Path $previewPath ('slide-{0:D2}.png' -f $slideIndex)
    $slide.Export($targetFile, 'PNG', 1920, 1080)
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($slide) | Out-Null
  }
  Write-Output ('Exported {0} slide previews to {1}' -f $deck.Slides.Count, $previewPath)
}
finally {
  if ($deck) {
    $deck.Close()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($deck) | Out-Null
  }
  if ($initialPresentationCount -eq 0 -and $powerPoint.Presentations.Count -eq 0) {
    $powerPoint.Quit()
  }
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) | Out-Null
}
