# Read a ZGY cube on your computer

A read procedure that converts a ZGY cube on your computer to SEG-Y rev 1 (IEEE samples). The SEG-Y lands as a
seismic volume; the server never reads ZGY. The conversion is `ophiolite.zgy.read`.

## Install

The procedure needs the optional package pyzgy:

```sh
pip install 'ophiolite[zgy]'
```

pyzgy installs segyio (LGPL-3.0-or-later). segyio has no wheel for Linux on ARM (aarch64), so the extra installs on
Linux x86_64 and on macOS, not on Linux aarch64.

## Register and run

The folder ships inside the SDK: `ophiolite.zgy.PROCEDURE` is its path. Register it in your project once, then
read the cube of an upload with it:

```sh
ophiolite procedures register "$(python -c 'import ophiolite.zgy as z; print(z.PROCEDURE)')"
ophiolite intake read RUN cube.zgy --keep-original --setting crs=EPSG:23031 --setting z_domain=time
```

The first read of a cube without the settings asks one question, before any sample is decoded: a ZGY states no
coordinate system, and often no vertical or horizontal unit. Answer it with the settings and read again:

| Setting | Values |
|---|---|
| `crs` | the coordinate system, for example `EPSG:23031` |
| `z_domain` | `time` (the file's vertical values in milliseconds) or `depth` (in metres) |
| `horizontal_unit` | `m`, needed only when the file does not state the unit of its coordinates |

## What is read, and what is refused

- The vertical axis is mapped exactly: time in milliseconds (whole milliseconds for the start, whole microseconds
  for the step) or depth in metres starting at 0. Seconds, feet, a fractional start or a step the SEG-Y header
  cannot hold are refused, naming the value. Nothing is rounded or rescaled.
- Horizontal coordinates must be metres. They are written with the coarsest SEG-Y coordinate scalar (-1, -10, -100
  or -1000) at which every trace coordinate is exact; a cube whose coordinates are not exact at -1000 (most rotated
  cubes) is refused, naming the coordinate.
- int8 and int16 cubes are scaled by their stated data range, as OpenZGY reads them.
- At most 32 MiB of ZGY, 1,000,000 traces, 20,000 samples per trace and 128 MiB of SEG-Y.
- The SEG-Y textual header keeps what the ZGY states (size, units, start, step, annotation, corners) and the
  original's SHA-256.

The OpenZGY test cubes are the format proof; a cube written by Petrel is not yet proven.
