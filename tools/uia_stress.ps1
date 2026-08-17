<#
uia_stress.ps1 [-Seconds <n>] [-Title <pattern>]

Drives Windows UI Automation (UIAutomationClient) against the HeadTracker
window to provoke the Qt6 accessibility bridge - the crash fingerprint seen
in python.exe.17336.dmp:

    user32 DispatchMessage -> UIAutomationCore.DLL -> Qt6Gui (a11y bridge)
      -> Qt6Widgets+0x600118 -> QMetaObject::activate -> AV read 0x7

Run this in a second console while the tracker is running (ideally tracking
with the tuning dialog open). If the tracker dies with a native exception
(CrashDumps\python.exe.*.dmp) while this script is walking the tree, the
UIA-trigger hypothesis is confirmed; if it survives several long runs, the
UIA path is exonerated.

Usage:
    powershell -ExecutionPolicy Bypass -File tools\uia_stress.ps1 -Seconds 300
#>
param(
    [int]$Seconds = 120,
    [string]$Title = "HeadTracker*"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$proc = Get-Process -Name python, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like $Title } |
    Select-Object -First 1
if (-not $proc) {
    Write-Error "HeadTracker window not found (title pattern '$Title'). Start the tracker first."
    exit 1
}

$root = [System.Windows.Automation.AutomationElement]::RootElement
$pidCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
    $proc.Id)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $pidCond)
if (-not $win) {
    Write-Error "No UIA window for pid $($proc.Id)"
    exit 2
}

$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$script:visits = 0
$deadline = (Get-Date).AddSeconds($Seconds)
$iterations = 0

function Touch([System.Windows.Automation.AutomationElement]$el) {
    $script:visits++
    try {
        $null = $el.Current.Name
        $null = $el.Current.ClassName
        $null = $el.Current.AutomationId
        $null = $el.Current.IsEnabled
        $null = $el.Current.IsOffscreen
        $null = $el.Current.BoundingRectangle
    } catch {
        # element died mid-query - exactly what we want to provoke
    }
}

function Walk([System.Windows.Automation.AutomationElement]$el, [int]$depth) {
    if ($depth -gt 4) { return }
    Touch $el
    try { $child = $walker.GetFirstChild($el) } catch { return }
    while ($child) {
        Walk $child ($depth + 1)
        try { $child = $walker.GetNextSibling($child) } catch { break }
    }
}

Write-Host "UIA stress on '$($win.Current.Name)' (pid $($proc.Id)), $Seconds s"

while ((Get-Date) -lt $deadline) {
    try {
        $null = $win.SetFocus()          # provoke focus/state events via the bridge
        Walk $win 0
        $null = $win.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    } catch {
        # window closed or bridge gone - reconnect if it still exists
        try { $null = $win.Current.Name } catch {
            Write-Host "Window lost; reconnecting..."
            $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $pidCond)
            if (-not $win) { Write-Host "Tracker gone - native crash likely."; exit 3 }
        }
    }
    $iterations++
    if ($iterations % 10 -eq 0) {
        Write-Host ("{0:HH:mm:ss} iterations={1} visits={2}" -f (Get-Date), $iterations, $script:visits)
    }
    Start-Sleep -Milliseconds 50
}

Write-Host "Done: iterations=$iterations visits=$script:visits (no crash provoked)"
