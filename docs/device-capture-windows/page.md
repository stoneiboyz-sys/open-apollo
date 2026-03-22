---
title: Device Capture (Windows)
---

This guide walks you through capturing device register data from your Apollo on Windows using WinRing0. This data helps us support Apollo models we don't have physical access to.

The capture script is **read-only** — it reads status and configuration registers from the device. It makes zero writes to hardware.

---

## What is WinRing0?

WinRing0 is an open-source kernel driver that provides userspace access to PCIe configuration space and memory-mapped I/O registers. It is widely used by hardware monitoring tools such as HWiNFO, Open Hardware Monitor, and LibreHardwareMonitor.

Source code: [https://github.com/GermanAizek/WinRing0](https://github.com/GermanAizek/WinRing0)

### Security considerations

WinRing0 installs a kernel-mode driver (`WinRing0x64.sys`) that allows userspace programs to read (and potentially write) hardware registers. This is a privileged capability. You should:

- Only install WinRing0 on a machine you trust
- Use the setup script provided, which installs to a known location
- Uninstall WinRing0 after capturing (instructions below)
- Verify the download hash matches what is documented

The capture script uses WinRing0 in **read-only mode** — it calls only read functions and never writes to any register.

---

## Step 1: Install WinRing0

Open **PowerShell as Administrator** and run the setup script:

```powershell
cd open-apollo\tools\contribute\windows
.\setup.ps1
```

The setup script downloads WinRing0, verifies the file hash, and installs the kernel driver service. It places files under `C:\Program Files\OpenApollo\WinRing0\`.

---

## Step 2: Run the capture

> **Note:** The Windows capture script is a work-in-progress placeholder and may not produce complete capture data yet. Partial captures are still useful — please submit what you get.

Make sure your Apollo is connected via Thunderbolt and powered on. UAD software should be installed (the driver must be active).

In the same Administrator PowerShell:

```powershell
python capture.py
```

Or with a custom output path:

```powershell
python capture.py --output C:\Users\You\Desktop\apollo-capture.json
```

The script will:

1. Verify it is running as Administrator
2. Check that WinRing0 is installed
3. Scan the PCI bus for a Universal Audio device
4. Read PCI configuration space (vendor ID, device ID, BAR addresses)
5. Read BAR0 status registers (firmware version, device type, serial, DSP status, sample rate)
6. Save everything to a JSON file

---

## Step 3: Review the capture

Before submitting, open the JSON file and review its contents. It contains:

- **System info**: Windows version, architecture, Python version
- **Device info**: Apollo model, PCI location, vendor/device IDs
- **PCI configuration**: Standard PCI identification fields
- **BAR0 registers**: Firmware version, device type, serial number, DSP status, sample rate

It does **not** contain: personal information, audio data, filesystem paths, user account names, or any data unrelated to the Apollo hardware.

---

## Step 4: Uninstall WinRing0

After capturing, remove WinRing0 from your system.

Open **PowerShell as Administrator**:

```powershell
Stop-Service -Name WinRing0_1_2_0 -Force
sc.exe delete WinRing0_1_2_0
Remove-Item -Recurse "$env:ProgramFiles\OpenApollo\WinRing0"
```

Restart your computer (optional but recommended).

Verify removal:

```powershell
Get-Service -Name WinRing0_1_2_0
# Should return: "Cannot find any service with service name..."
```

---

## What data is captured (technical details)

The capture script reads the following BAR0 register offsets:

| Register | Offset | Purpose |
|---|---|---|
| Firmware version | 0x0000 | Identifies firmware revision |
| FPGA revision | 0x2218 | Device type (bits[31:28]) and FPGA version |
| Extended caps | 0x2234 | Device type (bits[25:20]), DSP count (bits[15:8]) |
| Serial number | 0x2238 | For matching reports to devices |
| DSP status | 0x0040 | Whether DSP is running |
| Sequence counter (WR) | 0x3808 | DSP communication health (host → DSP) |
| Sequence counter (RD) | 0x380C | DSP communication health (DSP → host) |
| Sample rate | 0x0050 | Current audio sample rate |

It also reads the first 64 bytes of PCI configuration space, which contains standard PCI fields: vendor ID, device ID, BAR addresses, and subsystem information.

All reads use WinRing0's read-only functions. No writes are performed to any register.

See `tools/contribute/windows/WHAT-THIS-DOES.md` in the repository for additional details.

---

## Next steps

- [Submitting Your Data](/docs/submitting-data) — how to submit your capture
- [How to Contribute](/docs/how-to-contribute) — other ways to help
