param(
    [string]$Username,
    [string]$Password,
    [int]$Port
)

if ($PSBoundParameters.ContainsKey("Username")) {
    $env:APP_USERNAME = $Username
}
if ($PSBoundParameters.ContainsKey("Password")) {
    $env:APP_PASSWORD = $Password
}
if ($PSBoundParameters.ContainsKey("Port")) {
    $env:PORT = $Port
}

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python app.py
}
finally {
    Pop-Location
}
