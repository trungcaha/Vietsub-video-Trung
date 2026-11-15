$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupPy = Join-Path $ScriptDir "setup_machine.py"

$PythonBin = $null
$PrefixArgs = @()

foreach ($cmd in @("python", "python3", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        if ($cmd -eq "py") {
            & py -3 --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $PythonBin = "py"
                $PrefixArgs = @("-3")
                break
            }
        } else {
            $PythonBin = $found.Source
            break
        }
    }
}

if (-not $PythonBin -and (Test-Path "C:\Python313\python.exe")) {
    $PythonBin = "C:\Python313\python.exe"
}

if (-not $PythonBin) {
    Write-Error "Khong tim thay Python 3.10+. Vui long cai Python truoc khi chay install.ps1."
    exit 1
}

& $PythonBin @PrefixArgs $SetupPy @args
exit $LASTEXITCODE
