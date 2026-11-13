
## Visualization coordinates

New Registrar entries include `object.coordinatesV`, initially copied from
`object.coordinates`. Both use `epoch: J2000`, `ra_hms`, `dec_dms`, and optional
`ra_deg` / `dec_deg`. The editable preview validates and converts both pairs.

Only the sky map uses `coordinatesV`: both its center and named circle use this
pair. Certificate content and displayed catalogue coordinates always continue
to use `object.coordinates`. Historical entries without `coordinatesV` fall back
to normal coordinates. Clearing both visualization fields removes `coordinatesV`
and restores that fallback. An incomplete or invalid visual pair also falls back
as a pair; values from the two coordinate blocks are never mixed.
