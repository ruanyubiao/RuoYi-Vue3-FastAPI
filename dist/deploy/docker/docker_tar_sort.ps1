# Sorts the image lists in manifest.json and index.json inside a docker save tar, in place.
# docker save writes these lists in a random order; sorted, the same images give the same tar.
# The sorted text has the same byte length, so only those two files' bytes are rewritten.
param([Parameter(Mandatory=$true)][string]$Tar)
$ErrorActionPreference = 'Stop'

function Sort-JsonArray([string]$s, [int]$open) {
    $depth = 0; $inStr = $false; $esc = $false; $start = $open + 1; $close = -1
    $items = New-Object System.Collections.Generic.List[string]
    for ($i = $open + 1; $i -lt $s.Length; $i++) {
        $c = $s[$i]
        if ($inStr) {
            if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
            continue
        }
        if ($c -eq '"') { $inStr = $true }
        elseif ($c -eq '{' -or $c -eq '[') { $depth++ }
        elseif ($c -eq '}' -or $c -eq ']') {
            if ($depth -eq 0) { $items.Add($s.Substring($start, $i - $start)); $close = $i; break }
            $depth--
        }
        elseif ($c -eq ',' -and $depth -eq 0) { $items.Add($s.Substring($start, $i - $start)); $start = $i + 1 }
    }
    if ($close -lt 0) { throw 'unterminated JSON array' }
    $arr = $items.ToArray()
    [Array]::Sort($arr, [StringComparer]::Ordinal)
    return $s.Substring(0, $open + 1) + ($arr -join ',') + $s.Substring($close)
}

$fs = [IO.File]::Open($Tar, 'Open', 'ReadWrite')
try {
    $hdr = New-Object byte[] 512
    $found = 0
    while ($fs.Read($hdr, 0, 512) -eq 512) {
        if ($hdr[0] -eq 0) { break }
        $name = [Text.Encoding]::ASCII.GetString($hdr, 0, 100).TrimEnd([char]0)
        $size = [Convert]::ToInt64([Text.Encoding]::ASCII.GetString($hdr, 124, 12).Trim([char]0, ' '), 8)
        $pos = $fs.Position
        if ($name -eq 'manifest.json' -or $name -eq 'index.json') {
            $buf = New-Object byte[] $size
            $n = 0; while ($n -lt $size) { $r = $fs.Read($buf, $n, $size - $n); if ($r -le 0) { throw "short read in $name" }; $n += $r }
            $text = [Text.Encoding]::UTF8.GetString($buf)
            if ($name -eq 'manifest.json') { $open = $text.IndexOf('[') } else { $open = $text.IndexOf('"manifests":['); if ($open -ge 0) { $open += 12 } }
            if ($open -lt 0) { throw "image list not found in $name" }
            $out = [Text.Encoding]::UTF8.GetBytes((Sort-JsonArray $text $open))
            if ($out.Length -ne $size) { throw "$name changed length after sorting" }
            $fs.Position = $pos; $fs.Write($out, 0, $out.Length)
            $found++
        }
        $fs.Position = $pos + [long][Math]::Ceiling($size / 512) * 512
    }
    if ($found -lt 1) { throw 'manifest.json not found in tar' }
    Write-Output ('[OK] sorted image lists in {0} file(s) of {1}' -f $found, (Split-Path -Leaf $Tar))
} finally { $fs.Close() }