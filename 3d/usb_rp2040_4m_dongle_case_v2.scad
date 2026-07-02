/*
USB RP2040 (4M) dongle-style board enclosure - v2
Based on user's reference drawing.

Unit: mm

Reference dimensions read from the image:
- Main PCB body: 25.40 x 17.78 mm
- USB plug/tongue section length: 12.70 mm
- USB plug/tongue section width: 12.19 mm
- Total board length: 38.10 mm
- Pin row span shown: 20.32 mm

Design goal:
- Small and thin enclosure.
- Front USB plug area is considered: USB tongue is exposed, shell starts behind it.
- Rear wire harness exit hole is reserved.
- Two-piece shell: bottom tray + top cover.

Important:
Different USB RP2040 4M clones may vary slightly. First print a test ring or print at low height
to verify USB cutout and board fit before final printing.
*/

$fn = 48;

// ======================================================
// 1. Board parameters from image
// ======================================================
main_len = 25.40;          // right/main rounded PCB length
main_w   = 17.78;          // main PCB width
usb_len  = 12.70;          // left USB plug section length
usb_w    = 12.19;          // left USB plug section width
board_thick = 1.20;

// FDM clearance
fit_clearance = 0.35;      // per side
z_clearance = 0.25;

// ======================================================
// 2. Case dimensions
// ======================================================
wall = 1.10;               // minimum practical FDM wall, 0.4 nozzle ~3 lines
bottom_thick = 0.90;
top_thick = 0.90;
corner_r = 2.00;

// board vertical spaces
bottom_air = 0.70;
top_air = 3.10;            // room for chips / connector / solder
tray_z = bottom_thick + bottom_air + board_thick + top_air;   // ~5.9
cover_lip_z = 0.60;
total_z = tray_z + top_thick;                                 // ~6.8

// Shell only covers the main PCB body. USB plug stays exposed.
inner_len = main_len + fit_clearance * 2;
inner_w   = main_w + fit_clearance * 2;

outer_len = inner_len + wall * 2;     // ~29.0
outer_w   = inner_w + wall * 2;       // ~20.7

// USB-front opening. The case front wall has a notch for the 12.19 mm wide USB tongue.
usb_notch_w = usb_w + 0.80;
usb_notch_h = 2.60;                   // vertical opening near PCB plane
usb_notch_z = bottom_thick + bottom_air - 0.15;

// Rear wiring harness slot.
// If the actual cable is thicker, increase harness_slot_w / h.
harness_slot_w = 8.00;
harness_slot_h = 3.20;
harness_slot_z = bottom_thick + bottom_air + 0.40;

// Optional top connector window for wiring/soldering access.
top_wire_window = true;
top_window_len = 9.50;
top_window_w = 8.00;

// Optional small side relief slots for GPIO/soldered side wires.
side_wire_slots = false;
side_slot_len = 16.00;
side_slot_h = 2.20;
side_slot_z = bottom_thick + bottom_air + board_thick + 0.30;

// ======================================================
// 3. Helpers
// ======================================================
module rounded_box(l, w, z, r) {
    hull() {
        translate([r, r, 0]) cylinder(h=z, r=r);
        translate([l-r, r, 0]) cylinder(h=z, r=r);
        translate([l-r, w-r, 0]) cylinder(h=z, r=r);
        translate([r, w-r, 0]) cylinder(h=z, r=r);
    }
}

module usb_tongue_reference() {
    // Pure reference only, not printed unless enabled at bottom.
    color([0.02,0.02,0.02,0.35])
    translate([-usb_len, (outer_w-usb_w)/2, bottom_thick + bottom_air])
        cube([usb_len, usb_w, board_thick]);
}

module main_board_reference() {
    color([0,0.45,0.1,0.35])
    translate([wall + fit_clearance, wall + fit_clearance, bottom_thick + bottom_air])
        cube([main_len, main_w, board_thick]);
}

// ======================================================
// 4. Bottom tray
// ======================================================
module bottom_tray() {
    difference() {
        rounded_box(outer_len, outer_w, tray_z, corner_r);

        // Main board cavity, open from top
        translate([wall, wall, bottom_thick])
            cube([inner_len, inner_w, tray_z + 0.30]);

        // Front USB notch/opening at x=0.
        // This allows the exposed USB tongue to leave the enclosure.
        translate([-0.20, (outer_w-usb_notch_w)/2, usb_notch_z])
            cube([wall + 0.70, usb_notch_w, usb_notch_h]);

        // Rear wire harness outlet at x=outer_len.
        translate([outer_len - wall - 0.20, (outer_w-harness_slot_w)/2, harness_slot_z])
            cube([wall + 0.70, harness_slot_w, harness_slot_h]);

        // Optional long-side wire exits
        if (side_wire_slots) {
            translate([(outer_len-side_slot_len)/2, -0.20, side_slot_z])
                cube([side_slot_len, wall + 0.60, side_slot_h]);

            translate([(outer_len-side_slot_len)/2, outer_w-wall-0.30, side_slot_z])
                cube([side_slot_len, wall + 0.70, side_slot_h]);
        }
    }

    // Minimal board support ledges instead of screw posts to save space.
    // These avoid blocking parts on tiny boards.
    ledge_w = 1.00;
    ledge_h = 0.60;
    ledge_z = bottom_thick + bottom_air - ledge_h;

    translate([wall, wall, ledge_z])
        cube([inner_len, ledge_w, ledge_h]);

    translate([wall, wall + inner_w - ledge_w, ledge_z])
        cube([inner_len, ledge_w, ledge_h]);

    // Small rear stop to stop board sliding backward
    translate([outer_len - wall - 0.75, wall + 1.5, ledge_z])
        cube([0.75, inner_w - 3.0, ledge_h]);
}

// ======================================================
// 5. Top cover
// ======================================================
module top_cover() {
    lip_clearance = 0.18;

    difference() {
        union() {
            rounded_box(outer_len, outer_w, top_thick, corner_r);

            // Inset lip into tray
            translate([wall + lip_clearance, wall + lip_clearance, top_thick])
                cube([
                    inner_len - lip_clearance * 2,
                    inner_w   - lip_clearance * 2,
                    cover_lip_z
                ]);
        }

        // Front USB relief mirrored on cover
        translate([-0.20, (outer_w-usb_notch_w)/2, -0.10])
            cube([wall + 0.70, usb_notch_w, top_thick + cover_lip_z + 0.30]);

        // Rear wiring relief mirrored on cover
        translate([outer_len - wall - 0.20, (outer_w-harness_slot_w)/2, -0.10])
            cube([wall + 0.70, harness_slot_w, top_thick + cover_lip_z + 0.30]);

        // Optional top access window for rear connector / wire solder area
        if (top_wire_window) {
            translate([outer_len - top_window_len - 2.2, (outer_w-top_window_w)/2, -0.10])
                cube([top_window_len, top_window_w, top_thick + 0.30]);
        }
    }
}

// ======================================================
// 6. Print layout
// ======================================================
// Left: bottom tray
// Right: top cover
bottom_tray();

translate([outer_len + 8, 0, 0])
    top_cover();

// Uncomment for reference preview only:
// usb_tongue_reference();
// main_board_reference();
