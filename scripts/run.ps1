param(
    [string]$Username = "admin",
    [string]$Password = "admin",
    [int]$Port = 8080
)

$env:APP_USERNAME = $Username
$env:APP_PASSWORD = $Password
$env:PORT = $Port

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python app.py
}
finally {
    Pop-Location
}
