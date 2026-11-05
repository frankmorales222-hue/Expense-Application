# First-run configuration UI. Windows PowerShell 5.1 and built-in .NET only.
param([string]$AppDirectory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$envPath = Join-Path $AppDirectory '.env'
if (Test-Path -LiteralPath $envPath) {
    [void][System.Windows.Forms.MessageBox]::Show(
        'An existing .env was found and will not be overwritten. Close the app or stop its service, then edit that file to change connections. Its admin password setting is used only when creating the first account.',
        'Configuration already exists')
    exit 0
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'F&M Finance - First-time setup'
$form.ClientSize = New-Object System.Drawing.Size(620, 510)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Location = New-Object System.Drawing.Point(16, 16)
$tabs.Size = New-Object System.Drawing.Size(588, 425)
$form.Controls.Add($tabs)
$fields = @{}

function Add-Page([string]$title, [string]$text) {
    $page = New-Object System.Windows.Forms.TabPage
    $page.Text = $title
    $note = New-Object System.Windows.Forms.Label
    $note.Text = $text
    $note.Location = New-Object System.Drawing.Point(16, 16)
    $note.Size = New-Object System.Drawing.Size(548, 64)
    $page.Controls.Add($note)
    $tabs.TabPages.Add($page)
    return $page
}

function Add-Field($page, [int]$row, [string]$key, [string]$label, [string]$value, [bool]$secret = $false) {
    $y = 88 + $row * 44
    $caption = New-Object System.Windows.Forms.Label
    $caption.Text = $label
    $caption.Location = New-Object System.Drawing.Point(16, ($y + 3))
    $caption.Size = New-Object System.Drawing.Size(178, 30)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point(196, $y)
    $box.Size = New-Object System.Drawing.Size(354, 28)
    $box.Text = $value
    $box.UseSystemPasswordChar = $secret
    $page.Controls.Add($caption)
    $page.Controls.Add($box)
    $fields[$key] = $box
}

$db = Add-Page '1. Database' 'SQLite local testing is selected by default. Its database file is created automatically. Uncheck the option below to configure an existing PostgreSQL server.'
Add-Field $db 0 'dbHost' 'Server' 'localhost'
Add-Field $db 1 'dbPort' 'Port' '5432'
Add-Field $db 2 'dbName' 'Database' 'fm_finance'
Add-Field $db 3 'dbUser' 'Username' 'fm_user'
Add-Field $db 4 'dbPassword' 'Password' '' $true
$sqliteMode = New-Object System.Windows.Forms.CheckBox
$sqliteMode.Text = 'Use SQLite for local testing (no database installation)'
$sqliteMode.Checked = $true
$sqliteMode.Location = New-Object System.Drawing.Point(16, 328)
$sqliteMode.Size = New-Object System.Drawing.Size(548, 30)
$db.Controls.Add($sqliteMode)
$dbKeys = @('dbHost', 'dbPort', 'dbName', 'dbUser', 'dbPassword')
foreach ($key in $dbKeys) { $fields[$key].Enabled = $false }
$sqliteMode.Add_CheckedChanged({ foreach ($key in $dbKeys) { $fields[$key].Enabled = -not $sqliteMode.Checked } })
$storage = Add-Page '2. Receipts' 'Configure MinIO now or skip receipt storage while testing expenses. With MinIO, enter its S3 API endpoint (normally localhost:9000). Receipts stay private.'
Add-Field $storage 0 'endpoint' 'Endpoint (host:port)' 'localhost:9000'
Add-Field $storage 1 'accessKey' 'Access key' ''
Add-Field $storage 2 'secretKey' 'Secret key' '' $true
Add-Field $storage 3 'bucket' 'Bucket' 'expenses'
$tls = New-Object System.Windows.Forms.CheckBox
$tls.Text = 'MinIO uses HTTPS'
$tls.Location = New-Object System.Drawing.Point(196, 276)
$tls.Size = New-Object System.Drawing.Size(300, 30)
$storage.Controls.Add($tls)
$skipStorage = New-Object System.Windows.Forms.CheckBox
$skipStorage.Text = 'Configure receipt storage later (uploads disabled)'
$skipStorage.Checked = $true
$skipStorage.Location = New-Object System.Drawing.Point(16, 328)
$skipStorage.Size = New-Object System.Drawing.Size(548, 30)
$storage.Controls.Add($skipStorage)
$storageKeys = @('endpoint', 'accessKey', 'secretKey', 'bucket')
foreach ($key in $storageKeys) { $fields[$key].Enabled = $false }
$tls.Enabled = $false
$skipStorage.Add_CheckedChanged({
    foreach ($key in $storageKeys) { $fields[$key].Enabled = -not $skipStorage.Checked }
    $tls.Enabled = -not $skipStorage.Checked
})
$admin = Add-Page '3. Administrator' 'This account is created only if the database has no users. Choose a password of at least 10 characters. Change it in Settings after signing in.'
Add-Field $admin 0 'email' 'Email' 'admin@fmitai.com'
Add-Field $admin 1 'name' 'Name' 'Francisco Morales'
Add-Field $admin 2 'password' 'Password' '' $true
Add-Field $admin 3 'confirmation' 'Confirm password' '' $true
$save = New-Object System.Windows.Forms.Button
$save.Text = 'Save configuration'
$save.Location = New-Object System.Drawing.Point(394, 459)
$save.Size = New-Object System.Drawing.Size(210, 34)
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Cancel'
$cancel.Location = New-Object System.Drawing.Point(274, 459)
$cancel.Size = New-Object System.Drawing.Size(110, 34)
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($save)
$form.Controls.Add($cancel)
$form.CancelButton = $cancel

function Quote-Env([string]$value) {
    if ($value.Contains("`r") -or $value.Contains("`n") -or $value.Contains([char]0)) {
        throw 'Configuration values must not contain line breaks or null characters.'
    }
    return '"' + $value.Replace('\', '\\').Replace('"', '\"') + '"'
}

$save.Add_Click({
    try {
        foreach ($key in $fields.Keys) {
            if ($sqliteMode.Checked -and $key -in $dbKeys) { continue }
            if ($skipStorage.Checked -and $key -in $storageKeys) { continue }
            if ([string]::IsNullOrWhiteSpace($fields[$key].Text)) { throw 'Fill in every field on all three tabs.' }
            if ($fields[$key].Text.Contains('CHANGE_ME')) { throw 'Replace placeholder values before continuing.' }
        }
        if (-not $sqliteMode.Checked) {
        $port = 0
        if (-not [int]::TryParse($fields.dbPort.Text, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            throw 'Database port must be between 1 and 65535.'
        }
        $hostName = $fields.dbHost.Text.Trim()
        if ($hostName -notmatch '^[A-Za-z0-9.-]+$') { throw 'Enter a database hostname or IPv4 address without a URL scheme.' }
        }
        if ($fields.password.Text.Length -lt 10) { throw 'Administrator password must be at least 10 characters.' }
        if ($fields.password.Text -cne $fields.confirmation.Text) { throw 'Administrator passwords do not match.' }
        if ($fields.email.Text.Trim() -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { throw 'Enter a valid administrator email.' }
        $endpoint = $fields.endpoint.Text.Trim()
        if (-not $skipStorage.Checked -and $endpoint -notmatch '^[A-Za-z0-9.-]+:[0-9]+$') { throw 'MinIO endpoint must use host:port, for example localhost:9000.' }
        if (-not $skipStorage.Checked) {
        $s3Port = 0
        if (-not [int]::TryParse(($endpoint.Split(':')[1]), [ref]$s3Port) -or $s3Port -lt 1 -or $s3Port -gt 65535) {
            throw 'MinIO port must be between 1 and 65535.'
        }
        }
        $bytes = New-Object byte[] 48
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $jwt = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $connection = 'sqlite:///data/fm_finance.db'
        if (-not $sqliteMode.Checked) {
        $u = [Uri]::EscapeDataString($fields.dbUser.Text.Trim())
        $p = [Uri]::EscapeDataString($fields.dbPassword.Text)
        $d = [Uri]::EscapeDataString($fields.dbName.Text.Trim())
        $connection = "postgresql+psycopg2://${u}:${p}@${hostName}:${port}/${d}"
        }
        $minioAccess = if ($skipStorage.Checked) { '' } else { $fields.accessKey.Text }
        $minioSecret = if ($skipStorage.Checked) { '' } else { $fields.secretKey.Text }
        $values = [ordered]@{
            APP_HOST = '127.0.0.1'; APP_PORT = '8010'; APP_ENV = 'production'
            DATABASE_URL = $connection
            JWT_SECRET = $jwt; JWT_EXPIRE_HOURS = '12'; COOKIE_SECURE = 'false'
            ADMIN_EMAIL = $fields.email.Text.Trim(); ADMIN_NAME = $fields.name.Text.Trim()
            ADMIN_INITIAL_PASSWORD = $fields.password.Text
            MINIO_ENDPOINT = $endpoint; MINIO_ACCESS_KEY = $minioAccess
            MINIO_SECRET_KEY = $minioSecret; MINIO_SECURE = $tls.Checked.ToString().ToLowerInvariant()
            MINIO_BUCKET = $fields.bucket.Text.Trim(); MAX_RECEIPT_MB = '10'
            CURRENCY = 'USD'; APPROVAL_REQUIRED = 'false'; DEFAULT_APPROVAL_THRESHOLD = '500.00'; LOG_DIR = 'logs'
        }
        $lines = @('# F&M Finance configuration. Contains secrets; keep private.')
        foreach ($entry in $values.GetEnumerator()) { $lines += $entry.Key + '=' + (Quote-Env $entry.Value) }
        # CreateNew guarantees an existing configuration is never overwritten.
        $stream = [System.IO.File]::Open($envPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $encoding = New-Object System.Text.UTF8Encoding($false)
            $data = $encoding.GetBytes(($lines -join "`r`n") + "`r`n")
            $stream.Write($data, 0, $data.Length)
        } finally { $stream.Dispose() }
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Configuration could not be saved')
    }
})
$result = $form.ShowDialog()
$form.Dispose()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) { exit 0 }
exit 1
