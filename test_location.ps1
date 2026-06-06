Add-Type -AssemblyName System.Device
$geoWatcher = New-Object System.Device.Location.GeoCoordinateWatcher
# Use High accuracy, accept cached positions up to 10 minutes old
$null = $geoWatcher.TryStart($true, [TimeSpan]::FromMinutes(10))
# Wait up to 10 seconds for a fix
$timeout = 10
$elapsed = 0
while ($geoWatcher.Status -ne 'Ready' -and $elapsed -lt $timeout) {
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
}
if ($geoWatcher.Status -eq 'Ready') {
    $location = $geoWatcher.Position.Location
    Write-Output "{`"latitude`": $($location.Latitude), `"longitude`": $($location.Longitude)}"
} else {
    Write-Output "{`"error`": `"Location service not ready after ${timeout}s (status: $($geoWatcher.Status)). Enable location in Windows Settings > Privacy > Location`"}"
}
$geoWatcher.Stop()
