# Keep the launcher alive while the server runs, so upgrades can detect it.
param()
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$mutex = New-Object System.Threading.Mutex($false, 'Local\FMFinanceLauncher')
$ownsMutex = $false
$process = $null
try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) {
        [void][System.Windows.Forms.MessageBox]::Show('F&M Finance is already running. Use its browser window. To close it, use the F&M Finance tray icon.', 'F&M Finance')
        exit 0
    }
    $envPath = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        $configuration = Join-Path $PSScriptRoot 'configure.ps1'
        $setup = Start-Process -FilePath "$PSHOME\powershell.exe" -ArgumentList @('-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $configuration + '"')) -Wait -PassThru
        if ($setup.ExitCode -ne 0) { exit 0 }
    }
    $port = 8010
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
        if ($line -match '^\s*APP_PORT\s*=\s*["'']?(\d+)["'']?\s*(?:#.*)?$') { $port = [int]$Matches[1] }
    }
    if ($port -lt 1 -or $port -gt 65535) { throw 'APP_PORT must be between 1 and 65535.' }
    $url = "http://127.0.0.1:$port"
    # Never assume an existing listener belongs to this app.
    $probe = New-Object System.Net.Sockets.TcpClient
    $occupied = $false
    try {
        $occupied = $probe.ConnectAsync('127.0.0.1', $port).Wait(1000) -and $probe.Connected
    } catch {
        # Connection refused means the port is free.
    } finally { $probe.Dispose() }
    if ($occupied) {
        throw "Port $port is already in use. If the NSSM service is running, open $url directly. Otherwise stop the conflicting process or change APP_PORT in .env."
    }
    $exe = Join-Path $PSScriptRoot 'FMExpenseTracker.exe'
    $process = Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
        try {
            $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
            if ($health.database -eq 'ok' -and $health.version -eq '0.2.2') { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    if (-not $ready) {
        throw ('F&M Finance did not become ready. Check .env, PostgreSQL and MinIO. Startup logs are in the configured LOG_DIR (normally the logs folder beside the application).')
    }
    Start-Process $url
    # A tray icon lets the user open the browser or stop the local server.
    Add-Type -AssemblyName System.Drawing
    $tray = New-Object System.Windows.Forms.NotifyIcon
    $tray.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($exe)
    $tray.Text = 'F&M Finance'
    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $open = $menu.Items.Add('Open F&M Finance')
    $open.Add_Click({ Start-Process $url })
    $stop = $menu.Items.Add('Exit F&M Finance')
    $stop.Add_Click({ [System.Windows.Forms.Application]::ExitThread() })
    $tray.ContextMenuStrip = $menu
    $tray.Visible = $true
    $tray.Add_DoubleClick({ Start-Process $url })
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 1000
    $timer.Add_Tick({
        $process.Refresh()
        if ($process.HasExited) { [System.Windows.Forms.Application]::ExitThread() }
    })
    $timer.Start()
    try { [System.Windows.Forms.Application]::Run() }
    finally { $timer.Dispose(); $tray.Visible = $false; $tray.Dispose(); $menu.Dispose() }
} catch {
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'F&M Finance could not start')
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
