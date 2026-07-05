/*
  2.0 寸 ST7789 240x320 TFT + Raspberry Pi Pico 外壳
  单位：mm

  本版按你发的屏幕图纸重新校准：
    - 本次修改：LCD PCB 实际垫高高度改为 1.00mm；螺丝目标咬合深度设为 3.00mm；默认正面留 0.20mm 封底，实际塑料咬合约 2.80mm；Type-C 开孔保持在对向短边。
    - 结构说明：不要把 4.70mm 外径螺柱直接做到 3.00mm，否则会顶到 LCD PCB；本版改成“1mm 支撑台 + 底孔向前面板内延伸”。
    1. PCB 外形：37.10 x 62.00 x 1.20
    2. 屏幕四个安装孔：孔径 2.50；孔中心距横向 28.00，纵向 58.00
       注意：这里按“孔中心到孔中心”的 28 x 58 处理，不再把 58.00 当成底孔距顶边。
    3. 由 PCB 37.10 x 62.00 反推：孔中心距左右边约 4.55，距上下边约 2.00
    4. BL 外框参考：35.70 x 51.20，左右居中，上下按图纸 5.40 边距居中
    5. AA 有效显示区：30.60 x 40.80；AA 相对 BL 顶边下移 2.44

  重要说明：
    - 当前前面板真正看见的开窗默认按 AA 有效显示区做，并额外放大一点点，避免遮挡像素。
    - 前面板内侧增加了一个 BL 尺寸的浅避让槽，避免屏幕玻璃/背光框顶到前面板。
    - 如果你想前面直接露出整块黑色屏幕框，把 screen_window_use_bl 改成 true。
    - 如果打印后只剩上下微偏，优先微调 screen_window_y_extra_tune，正数往排针/上方移动，负数往下方移动。

  坐标方向：
    X = 屏幕宽度方向
    Y = 屏幕高度方向；+Y 是屏幕排针所在的顶边
    Z = 前面板外表面 -> 后盖方向

  part 可选：
    "print_plate" : 前壳和后盖同一打印平面摆放
    "front_shell" : 只导出前壳
    "back_cover"  : 只导出后盖
    "assembly"    : 装配预览
    "exploded"    : 爆炸预览

  打印建议：
    - FDM：0.2mm 层高，3 道墙，15%~25% 填充。
    - print_plate 模式下，前壳屏幕面朝下，后盖外侧朝下。
    - 后盖仍然是胶合/微凸点定位结构，不使用硬卡扣，避免装配变形。
*/

$fn = 56;
part = "print_plate";    // 可选："print_plate", "front_shell", "back_cover", "assembly", "exploded"

// ---------- 打印与装配余量 ----------
wall = 1.80;               // 外壳侧壁厚度
front_thick = 2.00;        // 前面板厚度
corner_r = 3.20;           // 外壳圆角
fit_clearance = 0.40;      // 屏幕 PCB 定位槽总余量，约等于单边 0.20
cover_clearance = 0.40;    // 后盖落入台阶的总余量，约等于单边 0.20
plate_gap = 12.00;         // 同板打印时两个零件之间的间距

// ---------- 屏幕模块：按图纸尺寸重新定义 ----------
screen_pcb_w = 37.10;
screen_pcb_h = 62.00;
screen_pcb_t = 1.20;
screen_hole_d = 2.50;

// 安装孔按你确认的孔中心距重新定义：横向 28mm，纵向 58mm。
// 之前错误点：把图上的 58.00 当成“底孔中心距 PCB 顶边”，会导致纵向孔距只有 48.70mm，螺柱看起来悬在中间。
screen_hole_dx = 28.00;
screen_hole_dy = 58.00;

// 下面两个数只用于校验和读图，不参与定位。
// 37.10 宽的 PCB，28.00 孔距 => 左右边到孔中心约 4.55mm。
// 62.00 高的 PCB，58.00 孔距 => 上下边到孔中心约 2.00mm。
screen_hole_edge_x = (screen_pcb_w - screen_hole_dx) / 2;
screen_hole_edge_y = (screen_pcb_h - screen_hole_dy) / 2;

// BL 是图纸中的外框参考尺寸，主要用于前面板内侧避让。
screen_bl_w = 35.70;
screen_bl_h = 51.20;
screen_bl_top_from_pcb_top = (screen_pcb_h - screen_bl_h) / 2;  // 5.40
screen_bl_y_offset = screen_pcb_h/2 - (screen_bl_top_from_pcb_top + screen_bl_h/2);

// AA 是有效显示区尺寸，默认前面板开窗按 AA 做。
screen_aa_w = 30.60;
screen_aa_h = 40.80;
screen_aa_top_from_bl_top = 2.44;
screen_aa_y_offset = screen_pcb_h/2 - (screen_bl_top_from_pcb_top + screen_aa_top_from_bl_top + screen_aa_h/2);

// 开窗设置：默认只露出有效显示区；若要露出整块 BL 外框，改成 true。
screen_window_use_bl = false;
screen_window_expand_w = 1.20;    // 开窗宽度额外放大，约单边 0.60
screen_window_expand_h = 1.20;    // 开窗高度额外放大，约单边 0.60
screen_window_y_extra_tune = 0.00; // 打印后微调用：正数往排针/上方，负数往下方
screen_window_w = (screen_window_use_bl ? screen_bl_w : screen_aa_w) + screen_window_expand_w;
screen_window_h = (screen_window_use_bl ? screen_bl_h : screen_aa_h) + screen_window_expand_h;
screen_window_y_offset = (screen_window_use_bl ? screen_bl_y_offset : screen_aa_y_offset) + screen_window_y_extra_tune;
screen_window_r = 1.20;

// OpenSCAD 控制台校验输出：渲染时会显示关键孔距和开窗尺寸。
echo(str("校验：屏幕孔中心距 X=", screen_hole_dx, "mm，Y=", screen_hole_dy, "mm；孔边距 X=", screen_hole_edge_x, "mm，Y=", screen_hole_edge_y, "mm"));
echo(str("校验：AA 可视区=", screen_aa_w, " x ", screen_aa_h, "mm；当前正面开窗=", screen_window_w, " x ", screen_window_h, "mm；开窗Y偏移=", screen_window_y_offset, "mm"));

// 前面板内侧给 BL 外框让位，不改变正面可视开窗大小。
screen_bl_relief_w = screen_bl_w + 0.80;
screen_bl_relief_h = screen_bl_h + 0.80;
screen_bl_relief_depth = 0.80;
screen_bl_relief_r = 1.20;

// 屏幕螺丝柱：屏幕从后侧用 M2 螺丝固定到前壳。
screen_boss_od = 4.70;
screen_support_h = 1.00;  // LCD PCB 实际垫高高度；屏幕背面实际坐在这个高度上
screen_boss_h = 3.00;     // 螺丝有效咬合深度目标，不等于外径 4.70mm 螺柱的实体高度
screen_boss_pilot_d = 1.55;   // M2 自攻底孔；如果要做通孔，可改成 2.20 左右
screen_pilot_bottom_skin = 0.20; // 底孔距前面板外表面保留的封底厚度；改 0 可得到完整 3mm 咬合但正面会穿孔
screen_thread_depth_actual = min(screen_boss_h, front_thick + screen_support_h - screen_pilot_bottom_skin); // 当前实际可咬合深度

// 屏幕 PCB 四周定位边。
screen_lip_t = 1.20;
screen_lip_h = screen_support_h + 1.10;

// ---------- 外壳尺寸 ----------
// 在屏幕 PCB 外形基础上加边框，避免手填尺寸造成整体比例偏差。
body_side_margin = 2.45;
body_top_bottom_margin = 3.00;
body_w = screen_pcb_w + 2*body_side_margin;
body_h = screen_pcb_h + 2*body_top_bottom_margin;
shell_depth = 18.00;       // 预留屏幕、走线和后盖上的 Pico 空间

// ---------- 后盖胶合台阶 ----------
cover_t = 2.20;
rear_edge_wall = wall / 2;        // 后口削薄后剩余的边墙厚度
rear_rebate_depth = cover_t;      // 后盖落入台阶的深度

inner_w = body_w - 2*wall;
inner_h = body_h - 2*wall;
rear_rebate_w = body_w - 2*rear_edge_wall;
rear_rebate_h = body_h - 2*rear_edge_wall;
cover_w = rear_rebate_w - cover_clearance;
cover_h = rear_rebate_h - cover_clearance;

// ---------- 后盖微凸点和前壳浅凹窝 ----------
// 这里不是硬卡扣，只做轻微定位；后盖最终建议点胶固定。
enable_arc_detents = true;
detent_bead_out = 0.45;          // 后盖边缘小弧形凸点突出量
detent_bead_r = 0.42;            // 凸点圆柱半径
detent_bead_len = 5.00;          // 凸点长度
detent_pocket_depth = 0.34;      // 前壳对应浅凹窝深度
detent_pocket_extra = 1.20;      // 凹窝比凸点略长，方便装配
detent_pocket_r_extra = 0.08;    // 凹窝半径余量
detent_side_overlap = 0.04;      // 避免布尔运算共面的小重叠

detent_long_y_frac = 0.24;       // 长边两个凸点的位置比例
enable_short_edge_detents = true; // 短边是否也增加一个居中凸点

// ---------- Raspberry Pi Pico RP2040 USB-C ----------
pico_pcb_w = 21.00;
pico_pcb_h = 51.00;
pico_pcb_t = 1.30;
pico_hole_dx = 11.50;
pico_hole_dy = 47.00;
pico_hole_d = 2.10;

// Pico 在后盖上的位置；Type-C 口位置由 Pico 的安装位置自动推导。
pico_usb_edge_inset = 1.10;
pico_usb_side_y = -1; // 本次改到对向侧：1 = Type-C 在 +Y 短边；-1 = Type-C 在 -Y 短边
pico_usb_edge_y = pico_usb_side_y * (body_h/2 - wall - pico_usb_edge_inset);
pico_center_y = pico_usb_edge_y - pico_usb_side_y * pico_pcb_h/2;
pico_center_x = 0;

// Pico 尾部两个 M2 螺丝柱。
pico_standoff_od = 5.00;
pico_standoff_h = 3.20;
pico_standoff_pilot_d = 1.55;

// Pico Type-C 一侧加宽支撑垫，避免 USB 一端悬空。
enable_pico_usb_support_pad = true;
pico_usb_pad_w = 18.00;
pico_usb_pad_h = 5.50;
pico_usb_pad_z = pico_standoff_h;

// ---------- Type-C 开孔 ----------
typec_open_w = 9.40;
typec_open_h = 3.80;
typec_open_r = typec_open_h/2 - 0.05;
typec_cut_depth = wall + 4.50;

typec_mouth_from_pico_usb_edge = 1.20; // Type-C 口相对 Pico 板边的伸出量
typec_center_from_pcb_front = 1.70;    // Type-C 中心到 Pico 正面元件面的距离

// 根据 Pico 装配高度推导 Type-C 开孔中心。
pico_mount_face_z = shell_depth - cover_t - pico_standoff_h;
pico_board_front_z = pico_mount_face_z - pico_pcb_t;
pico_board_center_z = pico_board_front_z + pico_pcb_t/2;
typec_open_x = pico_center_x;
typec_open_y = pico_usb_edge_y + pico_usb_side_y * typec_mouth_from_pico_usb_edge;
typec_open_center_z = pico_board_front_z - typec_center_from_pcb_front;

// OpenSCAD 控制台校验输出：本次修改后的 LCD 螺柱高度和 Type-C 侧向。
echo(str("校验：LCD 支撑高度=", screen_support_h, "mm；螺丝目标咬合深度=", screen_boss_h, "mm；Type-C 侧向=", pico_usb_side_y == 1 ? "+Y 短边" : "-Y 短边/对向侧", "；Type-C 开孔中心Y=", typec_open_y, "mm"));
echo(str("校验：LCD 底孔实际塑料咬合深度约=", screen_thread_depth_actual, "mm；正面封底厚度=", screen_pilot_bottom_skin, "mm"));

// ---------- 基础几何模块 ----------
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

// 侧边圆角 Type-C 开孔；截面在 X-Z 平面，沿 Y 方向切穿。
module side_typec_cut(w, h, depth, r, x = 0, y = 0, z = 0) {
  translate([x, y, z])
    rotate([90, 0, 0])
      linear_extrude(height = depth, center = true)
        round_rect_2d(w, h, r);
}

module at_screen_holes() {
  // 屏幕安装孔以 PCB 中心为坐标原点定位。
  // 横向中心距 = 28.00，所以 X = ±14.00。
  // 纵向中心距 = 58.00，所以 Y = ±29.00。
  // 这样四个螺柱会落在屏幕 PCB 四角附近，不会再悬在屏幕中间。
  for (x = [-screen_hole_dx/2, screen_hole_dx/2])
    for (y = [-screen_hole_dy/2, screen_hole_dy/2])
      translate([x, y, 0]) children();
}

module at_pico_tail_holes() {
  // Pico 尾部孔在 Type-C 的反方向。
  for (x = [-pico_hole_dx/2, pico_hole_dx/2])
    translate([pico_center_x + x, pico_center_y - pico_usb_side_y * pico_hole_dy/2, 0]) children();
}

module arc_bead_long_side(sx, y) {
  // 后盖长边弧形小凸点，大部分埋在后盖边缘里，只露出 detent_bead_out。
  bead_x = sx * (cover_w/2 + detent_bead_out - detent_bead_r);
  translate([bead_x, y, cover_t/2])
    rotate([90, 0, 0])
      cylinder(r = detent_bead_r, h = detent_bead_len, center = true);
}

module arc_bead_short_side(sy, x) {
  // 后盖短边弧形小凸点。
  bead_y = sy * (cover_h/2 + detent_bead_out - detent_bead_r);
  translate([x, bead_y, cover_t/2])
    rotate([0, 90, 0])
      cylinder(r = detent_bead_r, h = detent_bead_len, center = true);
}

module rear_cover_arc_detents() {
  if (enable_arc_detents) {
    // 长边：每边两个凸点。
    for (sx = [-1, 1])
      for (yf = [-detent_long_y_frac, detent_long_y_frac])
        arc_bead_long_side(sx, yf * cover_h);

    // 短边：每边一个居中凸点。
    if (enable_short_edge_detents)
      for (sy = [-1, 1])
        arc_bead_short_side(sy, 0);
  }
}

module arc_scoop_long_side(sx, y) {
  // 前壳后口长边浅凹窝，对应后盖凸点。
  pocket_r = detent_bead_r + detent_pocket_r_extra;
  pocket_len = detent_bead_len + detent_pocket_extra;
  pocket_center_x = sx * (rear_rebate_w/2 + detent_pocket_depth - pocket_r - detent_side_overlap);
  pocket_center_z = shell_depth - cover_t/2;
  translate([pocket_center_x, y, pocket_center_z])
    rotate([90, 0, 0])
      cylinder(r = pocket_r, h = pocket_len, center = true);
}

module arc_scoop_short_side(sy, x) {
  // 前壳后口短边浅凹窝，对应后盖凸点。
  pocket_r = detent_bead_r + detent_pocket_r_extra;
  pocket_len = detent_bead_len + detent_pocket_extra;
  pocket_center_y = sy * (rear_rebate_h/2 + detent_pocket_depth - pocket_r - detent_side_overlap);
  pocket_center_z = shell_depth - cover_t/2;
  translate([x, pocket_center_y, pocket_center_z])
    rotate([0, 90, 0])
      cylinder(r = pocket_r, h = pocket_len, center = true);
}

module front_shell_arc_scoop_cuts() {
  if (enable_arc_detents) {
    // 长边凹窝。
    for (sx = [-1, 1])
      for (yf = [-detent_long_y_frac, detent_long_y_frac])
        arc_scoop_long_side(sx, yf * cover_h);

    // 短边凹窝。
    if (enable_short_edge_detents)
      for (sy = [-1, 1])
        arc_scoop_short_side(sy, 0);
  }
}

// ---------- 前壳 ----------
module screen_locator_lips() {
  // 屏幕 PCB 四周定位边，按 PCB 外形加 fit_clearance 生成。
  x_lip = screen_pcb_w/2 + fit_clearance/2 + screen_lip_t/2;
  y_lip = screen_pcb_h/2 + fit_clearance/2 + screen_lip_t/2;

  // 左右定位边。
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
          -x_lip, 0, front_thick);
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
           x_lip, 0, front_thick);

  // 下边完整定位；上边避开排针区域，分成两段。
  add_box(screen_pcb_w + 2*screen_lip_t, screen_lip_t, screen_lip_h,
          0, -y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
          -(screen_pcb_w/4 + 1.50), y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
           (screen_pcb_w/4 + 1.50), y_lip, front_thick);
}

module rear_rabbet_cut() {
  // 后口削薄形成台阶，后盖落入这里再点胶。
  translate([0, 0, shell_depth - rear_rebate_depth])
    rounded_prism(rear_rebate_w, rear_rebate_h,
                  rear_rebate_depth + 0.80,
                  max(0.10, corner_r - rear_edge_wall));
}

module front_screen_inner_relief() {
  // 前面板内侧 BL 避让槽：不改变正面开窗，但给屏幕外框留空间。
  rounded_cut(screen_bl_relief_w, screen_bl_relief_h,
              screen_bl_relief_depth + 0.05, screen_bl_relief_r,
              0, screen_bl_y_offset,
              front_thick - screen_bl_relief_depth);
}

module front_shell() {
  difference() {
    union() {
      difference() {
        // 外壳主体。
        rounded_prism(body_w, body_h, shell_depth, corner_r);

        // 后侧主空腔，保留前面板和侧壁。
        translate([0, 0, front_thick])
          rounded_prism(inner_w, inner_h,
                        shell_depth - front_thick + 0.80,
                        max(0.10, corner_r - wall));

        // 后盖台阶。
        rear_rabbet_cut();

        // 正面可视开窗，默认按 AA 有效显示区对齐。
        rounded_cut(screen_window_w, screen_window_h,
                    front_thick + 1.20, screen_window_r,
                    0, screen_window_y_offset, -0.60);

        // 内侧 BL 避让槽。
        front_screen_inner_relief();
      }

      // 屏幕四个 M2 支撑台，中心距按 28 x 58 放置。
      // 外径 4.70mm 的部分只做到 screen_support_h，避免 LCD PCB 降低后被高螺柱顶住。
      at_screen_holes()
        translate([0, 0, front_thick])
          cylinder(d = screen_boss_od, h = screen_support_h);

      // 屏幕 PCB 定位边。
      screen_locator_lips();
    }

    // Type-C 侧边开孔。
    side_typec_cut(typec_open_w, typec_open_h, typec_cut_depth, typec_open_r,
                   typec_open_x, typec_open_y, typec_open_center_z);

    // 后盖凸点对应的前壳浅凹窝。
    front_shell_arc_scoop_cuts();

    // 屏幕 M2 自攻底孔。
    // 底孔从支撑台顶面向前面板内延伸，尽量获得接近 3mm 的咬合深度，同时保留正面封底不穿孔。
    screen_pilot_top_z = front_thick + screen_support_h + 0.35;
    screen_pilot_bottom_z = front_thick + screen_support_h - screen_thread_depth_actual;
    at_screen_holes()
      translate([0, 0, screen_pilot_bottom_z])
        cylinder(d = screen_boss_pilot_d, h = screen_pilot_top_z - screen_pilot_bottom_z);
  }
}

// ---------- 后盖 ----------
module back_cover() {
  difference() {
    union() {
      // 后盖板，落入前壳后口台阶。
      rounded_prism(cover_w, cover_h, cover_t, max(0.10, corner_r - rear_edge_wall - cover_clearance/2));

      // 后盖边缘弧形小凸点。
      rear_cover_arc_detents();

      // Pico 尾部两个螺丝柱。
      at_pico_tail_holes()
        translate([0, 0, cover_t])
          cylinder(d = pico_standoff_od, h = pico_standoff_h);

      // Pico USB 侧支撑垫。
      if (enable_pico_usb_support_pad)
        add_box(pico_usb_pad_w, pico_usb_pad_h, pico_usb_pad_z,
                pico_center_x, pico_usb_edge_y - pico_usb_side_y * (pico_usb_pad_h/2 + 2.00),
                cover_t);
    }

    // Pico M2 自攻底孔。
    at_pico_tail_holes()
      translate([0, 0, cover_t - 0.20])
        cylinder(d = pico_standoff_pilot_d, h = pico_standoff_h + 0.60);
  }
}

// ---------- 同平面打印布局 ----------
module print_plate() {
  // 左边前壳，屏幕面贴打印平台；右边后盖，外侧贴打印平台。
  translate([-(body_w/2 + plate_gap/2), 0, 0])
    front_shell();

  translate([(cover_w/2 + plate_gap/2), 0, 0])
    back_cover();
}

// ---------- 预览参考 ----------
module screen_reference() {
  // 屏幕 PCB 外形参考。
  color([0.0, 0.7, 0.1, 0.25])
    translate([0, 0, front_thick + screen_support_h + screen_pcb_t/2])
      cube([screen_pcb_w, screen_pcb_h, screen_pcb_t], center = true);

  // BL 外框参考。
  color([0.0, 0.0, 0.0, 0.18])
    translate([0, screen_bl_y_offset, 0.22])
      cube([screen_bl_w, screen_bl_h, 0.28], center = true);

  // AA 有效显示区参考。
  color([0.0, 0.0, 0.0, 0.35])
    translate([0, screen_aa_y_offset, 0.35])
      cube([screen_aa_w, screen_aa_h, 0.30], center = true);

  // 四个屏幕螺丝孔参考点：装配预览时用于核对 28 x 58 孔距。
  color([1.0, 0.0, 0.0, 0.65])
    at_screen_holes()
      translate([0, 0, front_thick + screen_support_h + screen_pcb_t + 0.25])
        cylinder(d = screen_hole_d, h = 0.50, center = true);
}

module pico_reference() {
  // Pico PCB 外形参考。
  color([0.05, 0.20, 0.90, 0.28])
    translate([pico_center_x, pico_center_y, pico_board_center_z])
      cube([pico_pcb_w, pico_pcb_h, pico_pcb_t], center = true);

  // Type-C 连接器大致位置参考。
  color([1.0, 0.45, 0.10, 0.55])
    translate([typec_open_x, typec_open_y, typec_open_center_z])
      cube([9.00, 4.00, 3.20], center = true);
}

module assembled_back_cover() {
  // 后盖装配预览：绕 Y 轴翻转，使后盖内部结构朝向前壳。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      back_cover();
}

// ---------- 导出选择 ----------
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

  // Type-C 开孔参考。
  color([1.0, 0.20, 0.10, 0.45])
    side_typec_cut(typec_open_w, typec_open_h, 1.80, typec_open_r,
                   typec_open_x, typec_open_y, typec_open_center_z);
}
