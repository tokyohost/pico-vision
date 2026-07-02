/*
Minimal landscape enclosure for 2.0" 240x320 TFT module
Based on supplied drawing:
- PCB: 37.10 ±0.20 x 62.00 ±0.20 mm
- PCB thickness: 1.20 mm
- Module max thickness: 6.00 mm
- BL/view area: 35.70 x 51.20 mm
- Cable slot: 12 x 1 mm

Orientation: landscape, so PCB becomes 62.0 W x 37.1 H.

Print note:
- For FDM 0.4 mm nozzle, 1.2 mm wall = 3 perimeters.
- Print front_shell face-down.
- First print a 1-layer test ring if your printer tolerance is unknown.
*/

$fn = 36;

// ---------- Parameters ----------
pcb_w_portrait = 37.10;
pcb_h_portrait = 62.00;
pcb_tol = 0.20;          // datasheet tolerance
fit_clearance = 0.30;    // clearance per side for 3D printing

// Landscape PCB maximum envelope
pcb_w = pcb_h_portrait + pcb_tol;   // 62.20
pcb_h = pcb_w_portrait + pcb_tol;   // 37.30

inner_w = pcb_w + fit_clearance * 2; // 62.80
inner_h = pcb_h + fit_clearance * 2; // 37.90

wall = 1.20;
front_lip = 1.00;
module_depth = 6.00;
depth_clearance = 0.40;

front_shell_z = front_lip + module_depth + depth_clearance; // 7.40
back_cover_z = 1.00;
total_z = front_shell_z + back_cover_z; // 8.40 if cover installed

outer_w = inner_w + wall * 2; // 65.20
outer_h = inner_h + wall * 2; // 40.30
corner_r = 2.00;

// Full BL/view window, rotated landscape.
// If you want only active AA area exposed, use 41.2 x 31.0 instead.
window_w = 51.20 + 0.40; // 51.60
window_h = 35.70 + 0.40; // 36.10

// Cable outlet on the connector side.
// Right side by default for landscape orientation; mirror model if your cable exits left.
cable_slot_len = 12.00;
cable_slot_h = 1.20;     // nominal 1 mm, enlarged to print reliably
cable_slot_z = 3.80;     // vertical position on side wall

// Optional cover fit
cover_inset_clearance = 0.20;
cover_inset_h = 0.60;

// ---------- Helpers ----------
module rounded_box(w, h, z, r) {
    hull() {
        translate([ r,  r, 0]) cylinder(h=z, r=r);
        translate([w-r, r, 0]) cylinder(h=z, r=r);
        translate([w-r, h-r, 0]) cylinder(h=z, r=r);
        translate([r, h-r, 0]) cylinder(h=z, r=r);
    }
}

// ---------- Parts ----------
module front_shell() {
    difference() {
        rounded_box(outer_w, outer_h, front_shell_z, corner_r);

        // Rear cavity for PCB/module, open from back
        translate([wall, wall, front_lip])
            cube([inner_w, inner_h, front_shell_z + 0.2], center=false);

        // Front display window
        translate([(outer_w-window_w)/2, (outer_h-window_h)/2, -0.1])
            cube([window_w, window_h, front_lip + 0.3], center=false);

        // Cable ribbon slot, 12 x ~1 mm, through right side wall
        translate([outer_w - wall - 0.2, (outer_h-cable_slot_len)/2, cable_slot_z])
            cube([wall + 0.6, cable_slot_len, cable_slot_h], center=false);
    }
}

module back_cover() {
    // Thin removable back cover with shallow inset lip
    union() {
        difference() {
            rounded_box(outer_w, outer_h, back_cover_z, corner_r);
            // tiny corner relief to avoid elephant-foot interference
        }
        translate([wall + cover_inset_clearance, wall + cover_inset_clearance, back_cover_z])
            cube([inner_w - cover_inset_clearance*2, inner_h - cover_inset_clearance*2, cover_inset_h], center=false);
    }
}

// Layout: front shell and cover side-by-side for export/printing.
// Export one module at a time if your slicer prefers separate STLs.
front_shell();

translate([outer_w + 8, 0, 0])
    back_cover();
