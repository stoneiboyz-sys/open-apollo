#!/bin/bash
# Record from Apollo Solo USB and save to Mac desktop.
# Usage: ./tools/usb-record.sh [seconds] [channel]
# Examples:
#   ./tools/usb-record.sh          # 10s, channel 0
#   ./tools/usb-record.sh 30       # 30s, channel 0
#   ./tools/usb-record.sh 15 1     # 15s, channel 1

SECS=${1:-10}
CH=${2:-0}
STAMP=$(date +%H%M%S)
OUTFILE=~/Desktop/apollo-ch${CH}-${STAMP}.wav
REMOTE_RAW=/tmp/apollo-raw.wav
REMOTE_MONO=/tmp/apollo-mono.wav

echo "Recording ${SECS}s from Apollo Solo USB channel ${CH}..."

ssh dev "timeout $((SECS + 1)) arecord -D hw:USB -f S32_LE -r 48000 -c 10 ${REMOTE_RAW} 2>/dev/null" 2>/dev/null

ssh dev "python3 -c \"
import wave, struct
w = wave.open('${REMOTE_RAW}', 'r')
n = w.getnframes(); ch = w.getnchannels()
data = w.readframes(n)
samples = struct.unpack('<' + 'i' * (n * ch), data)
mono = [samples[i * ch + ${CH}] for i in range(n)]
peak = max(abs(s) for s in mono)
print(f'{n} frames, peak={peak} ({20*__import__(\"math\").log10(peak/2147483647):.1f} dBFS)' if peak > 0 else f'{n} frames, silent')
out = wave.open('${REMOTE_MONO}', 'w')
out.setnchannels(1)
out.setsampwidth(4)
out.setframerate(48000)
out.writeframes(struct.pack('<' + 'i' * len(mono), *mono))
out.close()
w.close()
\"" 2>/dev/null

scp -q dev:${REMOTE_MONO} "${OUTFILE}" 2>/dev/null
echo "Saved: ${OUTFILE}"
