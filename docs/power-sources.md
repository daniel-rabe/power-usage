# Milestone 1: power sources on a Windows desktop

## What we need

Watts for the whole PC every few seconds, without extra hardware, from a
normal user session.

## Options checked

**LibreHardwareMonitor (LHM).** Open source, reads CPU package power (Intel
RAPL MSRs, AMD SMU) and GPU power (NVIDIA, AMD) plus many other sensors.
CPU power needs admin rights and LHM's kernel driver. Recent versions use the
PawnIO driver instead of the old WinRing0 one that Defender flags. Its
built-in web server publishes everything as JSON at
`http://localhost:8085/data.json`, so our logger can run without admin and
without loading .NET. **Chosen as the primary source.** Update: LibreHardwareMonitorLib (the same code as a .NET library, MPL-2.0) is now loaded in-process through pythonnet, so no second program has to run. It still needs administrator rights and the PawnIO driver (0.9.6 no longer uses WinRing0); the web server route stays as a fallback.

**NVML (`nvidia-ml-py`).** NVIDIA's official library. Board power for every
NVIDIA GPU, no admin needed, very cheap to call. **Used for the GPU when LHM
isn't running.** AMD has no equally simple Python route (ADLX is C++), so AMD
GPU power needs LHM.

**Windows Energy Meter counters (`\Energy Meter(*)\Power`, EMI).** Only exist
where the firmware exposes power meters, which is mostly laptops and some
Surface/ARM devices. Rare on desktops. `probe` reports whether this PC has
them; not used as a source for now.

**WMI `root\LibreHardwareMonitor` / `root\OpenHardwareMonitor`.** Same data as
the web server but needs pywin32/WMI and is slower. The web server is simpler.

**HWiNFO shared memory.** Good data, but the free version limits shared memory
to 12 hours at a time. Skipped.

**Utilization estimate.** CPU load x TDP from `psutil`. Always available,
often off by 30% or more. **Kept as the clearly flagged fallback.**

**Smart plug (Shelly, Tasmota, TP-Link Kasa).** The only way to get true wall
power including the PSU's losses. Needs a device; good optional source later.

## Result

```
total = CPU package (LHM) + GPU (LHM or NVML) + other_w (fixed, default 40 W)
```

If no source answers for a component, the estimate fills in and the sample is
stored with `estimated = 1`. Intel integrated GPU power is ignored because it
is already part of the CPU package.

Remember that this is the DC side. Wall draw is higher by the PSU's losses,
roughly 10-15% for an 80 Plus Gold unit; `other_w` absorbs part of that.

## Check your PC

```
python -m powerwidget probe
```

prints one line per source, for example:

```
lhm           OK  CPU 23.4 W, GPU 18.0 W
nvml          OK  CPU -, GPU 17.9 W
estimate      OK  CPU 21.0 W, GPU 15.0 W  (estimated)
energy_meter  no Energy Meter counters
```
