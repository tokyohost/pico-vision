/*
  Simple adhesive rear-cover enclosure for Raspberry Pi Pico RP2040 USB-C + 2.4 inch ST7789 240x320 TFT
  Unit: mm

  Revision:
    - No middle separator.
    - Screen module is inserted from the rear and fixed to the front shell by the screen's four PCB screw holes.
    - Rear cover has NO screws and NO snap tabs. It is a glue-in cover.
    - Rear edge of the front shell is half-thickness recessed, forming a simple rabbet/lap seat for the cover.
    - Rear cover drops into that half-wall recess and can be glued around the edge.
    - Rear cover carries the Pico, fixed only by the Pico tail two screw holes.
    - Shell bottom side has a rounded USB Type-C opening.
    - Front border is kept narrow by removing rear-cover screw posts and snap structures.
    - Avoids tiny slits / small latch features that are unreliable for FDM printing.

  Coordinate system:
    X = screen width
    Y = screen height; negative Y is the USB-C side
    Z = front -> rear

  Export:
    Change `part` below to:
      "print_plate" : front_shell and back_cover laid flat side-by-side on the same Z=0 print plane
      "front_shell" : front frame/tray, screen four bosses, Type-C opening, half-thickness rear rabbet
      "back_cover"  : glue-in rear cover with Pico tail two-screw standoffs
      "assembly"    : preview only
      "exploded"    : preview only

  Print suggestion:
    - FDM: 0.2 mm layer, 3 walls, 15~25% infill.
    - `print_plate` puts both printable parts on the same Z=0 plane.
    - front_shell is placed with the screen face on the bed.
    - back_cover is placed with the outside/back face on the bed, Pico standoffs upward.
    - Use thin double-sided tape / silicone / small hot-glue dots around the rear rabbet edge.
    - Avoid 502 near the display and USB-C connector.
*/

$fn = 56;
part = "print_plate";    // "print_plate", "front_shell", "back_cover", "assembly", "exploded"

// ---------- 3D printing / fit ----------
wall = 1.80;               // slim but still printable side wall
front_thick = 2.00;        // front face / bezel thickness
corner_r = 3.20;
fit_clearance = 0.40;      // screen PCB locator clearance
cover_clearance = 0.40;    // total XY clearance for the glue-in rear cover
plate_gap = 12.00;          // gap between front shell and back cover in print_plate mode

// ---------- Screen module, from your 2.4 inch ST7789 drawing ----------
screen_pcb_w = 42.72;
screen_pcb_h = 70.30;
screen_pcb_t = 1.20;
screen_hole_dx = 37.72;
screen_hole_dy = 65.30;
screen_hole_d = 2.10;

// Visible opening. Slightly larger than VA so the printed bezel does not cover pixels.
screen_va_w = 37.42;
screen_va_h = 49.66;
screen_window_w = screen_va_w + 1.60;
screen_window_h = screen_va_h + 2.20;
screen_window_y_offset = -3.00;     // tune if your display active area is shifted
screen_window_r = 1.20;

// Screen screw bosses in the front shell. Screen is screwed from the rear into these bosses.
screen_boss_od = 4.70;
screen_boss_h = 3.00;
screen_boss_pilot_d = 1.55;         // M2 self-tapping pilot; change to 2.20 for through-hole

// Simple solid screen PCB locator lips. No tiny decorative grooves.
screen_lip_t = 1.20;
screen_lip_h = screen_boss_h + 1.10;

// ---------- Enclosure size ----------
// Kept close to the screen PCB size to reduce the visual border.
body_w = 47.20;
body_h = 76.20;
shell_depth = 18.00;       // enough for screen PCB + wiring + Pico on rear cover

// ---------- Recessed adhesive rear cover ----------
cover_t = 2.20;

// Rear-cover rabbet / lap joint:
// the rear edge of the front shell is thinned to about 1/2 wall thickness.
// The cover sits into this larger rear recess instead of only fitting inside the full inner cavity.
// This avoids card扣/螺丝 and keeps the visible frame slim.
rear_edge_wall = wall / 2;        // remaining rear rim thickness after cutting the shell edge thinner
rear_rebate_depth = cover_t;      // depth of the cover seat; normally equal to cover thickness

inner_w = body_w - 2*wall;
inner_h = body_h - 2*wall;
rear_rebate_w = body_w - 2*rear_edge_wall;
rear_rebate_h = body_h - 2*rear_edge_wall;
cover_w = rear_rebate_w - cover_clearance;
cover_h = rear_rebate_h - cover_clearance;

// ---------- Raspberry Pi Pico RP2040 USB-C, from your Pico drawing ----------
pico_pcb_w = 21.00;
pico_pcb_h = 51.00;
pico_pcb_t = 1.30;
pico_hole_dx = 11.50;
pico_hole_dy = 47.00;       // please measure your actual Pico board if possible
pico_hole_d = 2.10;

// Pico placement on the rear cover.
// USB-C side is the negative-Y end. It sits near the bottom Type-C opening.
pico_usb_edge_inset = 1.10;
pico_usb_edge_y = -body_h/2 + wall + pico_usb_edge_inset;
pico_center_y = pico_usb_edge_y + pico_pcb_h/2;
pico_center_x = 0;

// Pico tail screw standoffs on the rear cover.
pico_standoff_od = 5.00;
pico_standoff_h = 3.20;
pico_standoff_pilot_d = 1.55;       // M2 self-tapping pilot

// Broad support pad near Pico USB side. This prevents the USB side from floating.
// It is intentionally a solid pad, not a thin rail.
enable_pico_usb_support_pad = true;
pico_usb_pad_w = 18.00;
pico_usb_pad_h = 5.50;
pico_usb_pad_z = pico_standoff_h;

// ---------- USB-C opening ----------
// Rounded Type-C shaped side opening, not a square hole.
// Tune width/height after measuring your real connector and printer shrinkage.
typec_open_w = 10.80;
typec_open_h = 4.80;
typec_open_r = typec_open_h/2 - 0.05;
typec_cut_depth = wall + 4.50;

// Connector center in Z when Pico is mounted on the recessed rear cover.
// Adjust this if the plug is visually high/low after a draft print.
typec_center_from_pcb_front = 1.70;
pico_board_center_z = shell_depth - cover_t - pico_standoff_h - pico_pcb_t/2;
typec_open_center_z = pico_board_center_z - pico_pcb_t/2 - typec_center_from_pcb_front;
typec_open_y = -body_h/2 + wall/2;

// ---------- Helper modules ----------
module round_rect_2d(w, h, r) {
  rr = min(r, min(w, h)/2 - 0.01);
  offset(r = rr) square([w - 2*rr, h - 2*rr], center = true);
}

module rounded_prism(w, h, z, r) {
  linear_extrude(height = z)
    round_rect_2d(w, h, r);
}

module add_box(w, h, z, x = 0, y = 0, z0 = 0) {
  translate([x - w/2, y - h/2, z0]) cube([w, h, z]);
}

module rounded_cut(w, h, z, r, x = 0, y = 0, z0 = 0) {
  translate([x, y, z0])
    linear_extrude(height = z)
      round_rect_2d(w, h, r);
}

// Rounded port cut on bottom side wall. Shape profile is X-Z; extrusion direction is Y.
module side_typec_cut(w, h, depth, r, x = 0, y = 0, z = 0) {
  translate([x, y, z])
    rotate([90, 0, 0])
      linear_extrude(height = depth, center = true)
        round_rect_2d(w, h, r);
}

module at_screen_holes() {
  for (x = [-screen_hole_dx/2, screen_hole_dx/2])
    for (y = [-screen_hole_dy/2, screen_hole_dy/2])
      translate([x, y, 0]) children();
}

module at_pico_tail_holes() {
  // USB-C is at negative Y, tail holes are at positive Y end.
  for (x = [-pico_hole_dx/2, pico_hole_dx/2])
    translate([pico_center_x + x, pico_center_y + pico_hole_dy/2, 0]) children();
}

// ---------- Front shell ----------
module screen_locator_lips() {
  // Broad locator lips, intentionally simple and printable.
  x_lip = screen_pcb_w/2 + fit_clearance/2 + screen_lip_t/2;
  y_lip = screen_pcb_h/2 + fit_clearance/2 + screen_lip_t/2;

  // Left/right lips
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
          -x_lip, 0, front_thick);
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
           x_lip, 0, front_thick);

  // Bottom lip. Top lip is split so the screen header/wires have more room.
  add_box(screen_pcb_w + 2*screen_lip_t, screen_lip_t, screen_lip_h,
          0, -y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
          -(screen_pcb_w/4 + 1.50), y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
           (screen_pcb_w/4 + 1.50), y_lip, front_thick);
}

module rear_rabbet_cut() {
  // Cut the rear edge larger than the main internal cavity.
  // This creates a half-wall-thickness step so the rear cover can drop into the shell.
  // The bottom of this cut is the cover seating ledge.
  translate([0, 0, shell_depth - rear_rebate_depth])
    rounded_prism(rear_rebate_w, rear_rebate_h,
                  rear_rebate_depth + 0.80,
                  max(0.10, corner_r - rear_edge_wall));
}

module front_shell() {
  difference() {
    union() {
      difference() {
        // Outside body.
        rounded_prism(body_w, body_h, shell_depth, corner_r);

        // Main rear hollow cavity; leaves front face and full side walls.
        translate([0, 0, front_thick])
          rounded_prism(inner_w, inner_h,
                        shell_depth - front_thick + 0.80,
                        max(0.10, corner_r - wall));

        // Half-thickness rear rabbet for the glue-in cover.
        // This is the actual "cut thin 1/2 wall" feature.
        rear_rabbet_cut();

        // Front screen window.
        rounded_cut(screen_window_w, screen_window_h,
                    front_thick + 1.20, screen_window_r,
                    0, screen_window_y_offset, -0.60);
      }

      // Four screen bosses for M2 screws.
      at_screen_holes()
        translate([0, 0, front_thick])
          cylinder(d = screen_boss_od, h = screen_boss_h);

      // Simple screen PCB locator pocket.
      screen_locator_lips();

    }

    // Type-C side opening. Cut through shell and shelf if they overlap.
    side_typec_cut(typec_open_w, typec_open_h, typec_cut_depth, typec_open_r,
                   0, typec_open_y, typec_open_center_z);

    // Screen M2 pilot holes.
    at_screen_holes()
      translate([0, 0, front_thick - 0.30])
        cylinder(d = screen_boss_pilot_d, h = screen_boss_h + 0.80);
  }
}

// ---------- Rear cover with Pico tail mounting, glue-in style ----------
module back_cover() {
  difference() {
    union() {
      // Cover plate. It drops into the half-thickness rear rabbet and glues around the edge.
      rounded_prism(cover_w, cover_h, cover_t, max(0.10, corner_r - rear_edge_wall - cover_clearance/2));

      // Two Pico tail standoffs on the inner side of the cover.
      at_pico_tail_holes()
        translate([0, 0, cover_t])
          cylinder(d = pico_standoff_od, h = pico_standoff_h);

      // Broad USB-side support pad for Pico. Solid and easy to print.
      if (enable_pico_usb_support_pad)
        add_box(pico_usb_pad_w, pico_usb_pad_h, pico_usb_pad_z,
                pico_center_x, pico_usb_edge_y + pico_usb_pad_h/2 + 2.00,
                cover_t);
    }

    // Pico tail M2 pilot holes in the two standoffs.
    at_pico_tail_holes()
      translate([0, 0, cover_t - 0.20])
        cylinder(d = pico_standoff_pilot_d, h = pico_standoff_h + 0.60);
  }
}


// ---------- Same-plane 3D-print layout ----------
module print_plate() {
  // Both parts are on the same Z=0 plane.
  // Left: front_shell, screen/front face touching the bed.
  // Right: back_cover, outside/back face touching the bed, Pico standoffs upward.
  translate([-(body_w/2 + plate_gap/2), 0, 0])
    front_shell();

  translate([(cover_w/2 + plate_gap/2), 0, 0])
    back_cover();
}

// ---------- Preview references ----------
module screen_reference() {
  // Approximate screen PCB envelope. Display side faces front.
  color([0.0, 0.7, 0.1, 0.25])
    translate([0, 0, front_thick + screen_boss_h + screen_pcb_t/2])
      cube([screen_pcb_w, screen_pcb_h, screen_pcb_t], center = true);

  // Active window reference.
  color([0.0, 0.0, 0.0, 0.35])
    translate([0, screen_window_y_offset, 0.15])
      cube([screen_window_w, screen_window_h, 0.30], center = true);
}

module pico_reference() {
  color([0.05, 0.20, 0.90, 0.28])
    translate([pico_center_x, pico_center_y, pico_board_center_z])
      cube([pico_pcb_w, pico_pcb_h, pico_pcb_t], center = true);

  // Type-C connector rough envelope near USB side.
  color([1.0, 0.45, 0.10, 0.55])
    translate([pico_center_x, pico_usb_edge_y - 1.20, typec_open_center_z])
      cube([9.00, 4.00, 3.20], center = true);
}

module assembled_back_cover() {
  // Rotate cover so its inner features point into the shell.
  // Outside/back face becomes flush with shell rear at Z = shell_depth.
  translate([0, 0, shell_depth])
    rotate([180, 0, 0])
      back_cover();
}

// ---------- Part selector ----------
if (part == "print_plate") {
  print_plate();
} else if (part == "front_shell") {
  front_shell();
} else if (part == "back_cover") {
  back_cover();
} else if (part == "exploded") {
  translate([0, 0, 0]) front_shell();
  translate([0, 0, 27]) back_cover();
  translate([0, 0, 0]) screen_reference();
} else {
  color([0.86, 0.86, 0.86, 1.0]) front_shell();
  color([0.70, 0.70, 0.70, 0.85]) assembled_back_cover();
  screen_reference();
  pico_reference();

  // Type-C opening reference.
  color([1.0, 0.20, 0.10, 0.45])
    side_typec_cut(typec_open_w, typec_open_h, 1.80, typec_open_r,
                   0, typec_open_y - 1.30, typec_open_center_z);
}
