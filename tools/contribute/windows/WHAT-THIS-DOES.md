# Windows Capture Script — What This Does

This document explains exactly what `setup.ps1` and `capture.py` do, so you
can make an informed decision before running them.

## What is WinRing0?

**WinRing0** is an open-source kernel driver that provides userspace access to
PCIe configuration space and memory-mapped I/O registers on Windows. It is
widely used by hardware monitoring tools such as HWiNFO, Open Hardware Monitor,
and LibreHardwareMonitor.

WinRing0 installs a small kernel-mode driver (`WinRing0x64.sys`) that acts as
a bridge — userspace applications send read requests through it to access
hardware registers that are normally only accessible from kernel mode.

Source code: https://github.com/GermanAizek/WinRing0

## Why is WinRing0 needed?

Windows does not allow userspace programs to directly read PCIe device
registers. The Apollo's device type, serial number, firmware version, and
audio routing configuration are stored in memory-mapped registers (BAR0) on
the PCIe device. WinRing0 provides the bridge to read these values.

## What registers are read?

The capture script reads **status and configuration registers only**:

| Register | Offset | Purpose |
|----------|--------|---------|
| Firmware version | 0x0004 | Identifies firmware revision |
| Device type | 0x0008 | Identifies Apollo model (x4, x6, x8, etc.) |
| Serial number | 0x000C | Device serial (for matching reports) |
| DSP status | 0x0040 | Whether DSP is running |
| Sequence counter | 0x0018 | DSP communication health indicator |
| Sample rate | 0x0050 | Current audio sample rate |

Additionally, the script reads the **PCI configuration space** (first 64 bytes),
which contains standard PCI identification fields: vendor ID, device ID, BAR
addresses, and subsystem information.

## What this does NOT do

- **ZERO writes to hardware** — The script only reads registers. It never
  writes to any BAR0 offset, PCI config register, or any other hardware
  address. All WinRing0 calls use read-only functions.
- **No network calls** — All output is saved to a local JSON file. Nothing
  is uploaded or sent anywhere.
- **No system modifications** — Beyond the WinRing0 driver installation
  (which you control), no system files are changed.
- **No audio data** — The script does not access DMA buffers or audio
  streams. It reads only configuration/status registers.

## Output

The script produces a single JSON file containing hardware identifiers and
register values. You can (and should) review this file before submitting it.
It contains no personal information, no audio data, and no filesystem paths.

## How to uninstall WinRing0

After capturing, you can remove WinRing0 completely:

1. Open **PowerShell as Administrator**
2. Run these commands:

```powershell
Stop-Service -Name WinRing0_1_2_0 -Force
sc.exe delete WinRing0_1_2_0
Remove-Item -Recurse "$env:ProgramFiles\OpenApollo\WinRing0"
```

3. Restart your computer (optional but recommended)

You can verify removal with:
```powershell
Get-Service -Name WinRing0_1_2_0
# Should return an error: "Cannot find any service with service name..."
```
