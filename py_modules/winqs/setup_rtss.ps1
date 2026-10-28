# One-time setup (run elevated) so the plugin, which runs without administrator rights, can use RTSS's
# frame limiter for every game (DX9/11/12, Vulkan, OpenGL):
#   1. the given user may change RTSS profiles (Profiles folder is admin-only by default);
#   2. RTSS (requireAdministrator) starts elevated at logon through a scheduled task, and the same user may
#      start that task on demand (schtasks /run), so the plugin can launch RTSS without a UAC prompt.
# Nothing else is changed. Undo: Unregister-ScheduledTask -TaskName 'WinQS RTSS'; icacls <Profiles> /remove <user>
#
# The plugin folder is writable by the user, so this file is never run from disk: service.setup_rtss() reads it when
# the backend starts and passes it to the elevated PowerShell with -EncodedCommand. The script trusts no path it is
# given: it finds RTSS in the registry itself and only accepts a signed RTSS.exe inside Program Files (admin-only), so
# the elevated task can never point at a file the user could replace. It writes no log: an elevated process writing
# into a user folder could be redirected to overwrite another file. The plugin sees the result in RTSS's status.
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^S-1-\d+(-\d+)+$')][string]$UserSid
)
$ErrorActionPreference = 'Stop'

# where RTSS is installed: RTSS's own registry record (admin-writable only), else the standard folder
$rtss = $null
try { $rtss = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\WOW6432Node\Unwinder\RTSS' -Name InstallDir).InstallDir } catch { }
if (-not $rtss) { $rtss = Join-Path ${env:ProgramFiles(x86)} 'RivaTuner Statistics Server' }
$rtss = [IO.Path]::GetFullPath($rtss).TrimEnd('\')
$roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles) | Where-Object { $_ } | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') + '\' }
if (-not ($roots | Where-Object { $rtss.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) {
    throw "RTSS is not installed under Program Files ($rtss)"
}
$exe = Join-Path $rtss 'RTSS.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "RTSS not found in $rtss" }
$sig = Get-AuthenticodeSignature -LiteralPath $exe
if ($sig.Status -ne 'Valid') { throw "RTSS.exe is not validly signed ($($sig.Status))" }
$user = (New-Object System.Security.Principal.SecurityIdentifier($UserSid)).Translate([System.Security.Principal.NTAccount]).Value

# 1. profile access for this user only
& "$env:SystemRoot\System32\icacls.exe" (Join-Path $rtss 'Profiles') /grant "*${UserSid}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }

# 2. elevated autostart at this user's logon
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $rtss
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'WinQS RTSS' -TaskPath '\' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description 'Starts RivaTuner Statistics Server for the Windows Quick Settings Decky plugin (frame limit).' -Force | Out-Null

# let the user start (read + execute) the task without elevation
$svc = New-Object -ComObject 'Schedule.Service'
$svc.Connect()
$task = $svc.GetFolder('\').GetTask('WinQS RTSS')
$task.SetSecurityDescriptor("D:(A;;FA;;;BA)(A;;FA;;;SY)(A;;GRGX;;;$UserSid)", 0)

Start-ScheduledTask -TaskName 'WinQS RTSS'
