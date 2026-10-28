# Device-label photos for the vision demo

Put device-label photos here (`.jpg`, `.jpeg`, `.png`, `.webp`). Pushing them
to `hackathon-day2` runs `.github/workflows/vision-labels.yml`, which reads each
photo with SAM 3.1 → Muse Spark → openFDA and commits `demo/vision/label-<name>.json`.

Rules (this is a public repository):

1. **No serial number or QR code may be visible.** Crop or cover them before the
   photo is committed. The reader also never stores lot or serial numbers, but
   the photo itself would show them.
2. **Strip metadata first** (camera, GPS, time):
   `python3.12 scripts/prepare_label_photo.py IMG_1234.jpg demo/vision/labels/label-1.jpg`.
   The workflow refuses to run if any photo still carries metadata.
3. **Push the photos alone**, in their own commit, so the run is clearly separate.
4. No patient information anywhere in the frame.
