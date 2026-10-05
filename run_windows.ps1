 = 'Stop'
Set-Location 
 = 
if (Get-Command py -ErrorAction SilentlyContinue) {
    py start.py @argsToPass
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python start.py @argsToPass
} else {
    throw 'Python 3.11+ was not found. Install Python and run this script again.'
}
