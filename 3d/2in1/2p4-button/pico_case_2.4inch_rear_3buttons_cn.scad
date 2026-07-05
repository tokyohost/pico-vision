/*
  Raspberry Pi Pico RP2040 USB-C + 2.4 寸 ST7789 240x320 TFT 简易后盖粘合式外壳
  版本：弧形小凸包 + 封闭弧形凹窝，无导槽入口
  单位：mm

  本版改动：
    - 取消中间隔板。
    - 屏幕模块从后方装入，并通过屏幕 PCB 的 4 个螺丝孔固定到前壳。
    - 后盖没有螺丝固定外壳，也没有硬卡扣；只使用微小弧形定位凸包和对应的封闭浅弧凹窝。
    - 前壳后沿做半壁厚台阶，形成后盖的搭接/落座台阶。
    - 后盖落入半壁厚台阶后，可沿边缘点胶固定。
    - Pico 固定在后盖上，只使用 Pico 尾部 2 个螺丝孔。
    - 外壳对侧短边开圆角 USB Type-C 孔。
    - 去掉后盖螺丝柱和硬卡扣结构，使前框边缘尽量窄。
    - 不使用导槽入口，只保留后盖边缘弧形凸包和前壳后唇封闭弧形凹窝。
    - 后盖新增 3 个按键键帽孔。
    - 后盖内侧新增 3 个 12x12 微动开关限位框。
    - 后盖内侧新增 2 个按键盖板螺柱。
    - 新增独立按键盖板，盖板上有 2 个 M2 过孔、每个开关对应 4 个小孔和 1 个中间避让孔。

  坐标系：
    X = 屏幕宽度方向
    Y = 屏幕高度方向；本版本中 Y 正方向是 USB-C 所在侧
    Z = 前面板 -> 后盖方向

  导出方式：
    修改下面的 `part` 变量：
      "print_plate"  : 前壳、后盖、按键盖板放在同一 Z=0 打印平面
      "front_shell"  : 前框/托盘，含屏幕 4 个螺柱、Type-C 孔、后沿半壁厚台阶
      "back_cover"   : 粘合式后盖，含 Pico 尾部 2 个螺柱、3 个按键孔、按键限位和按键盖板螺柱
      "button_plate" : 3 个微动开关用的独立按键压板/盖板
      "assembly"     : 仅用于装配预览
      "exploded"     : 仅用于爆炸预览

  打印建议：
    - FDM：0.2 mm 层高，3 道壁，15~25% 填充。
    - `print_plate` 会把所有可打印零件放在同一 Z=0 平面。
    - front_shell 以前面/屏幕面贴床打印。
    - back_cover 以后盖外表面贴床打印，Pico 螺柱和按键结构朝上。
    - button_plate 是独立薄盖板，用于压住 3 个微动开关。
    - 后盖带微小弧形定位凸包，前壳带匹配的封闭浅弧凹窝；没有导槽入口。
    - 如需更稳，可在后盖台阶边缘使用薄双面胶、硅胶或少量热熔胶点胶。
    - 避免在显示屏和 USB-C 接口附近使用 502。
*/

$fn = 56;
part = "print_plate";    // "print_plate", "front_shell", "back_cover", "button_plate", "assembly", "exploded"

// ---------- 3D 打印 / 装配间隙 ----------
wall = 1.80;               // 侧壁厚度，尽量薄但仍便于打印
front_thick = 2.00;        // 前面板/边框厚度
corner_r = 3.20;
fit_clearance = 0.40;      // 屏幕 PCB 定位间隙
cover_clearance = 0.40;    // 粘合式后盖的 XY 总间隙
plate_gap = 12.00;          // print_plate 模式下前壳和后盖之间的间距

// ---------- 屏幕模块，来自你的 2.4 寸 ST7789 图纸 ----------
screen_pcb_w = 42.72;
screen_pcb_h = 70.30;
screen_pcb_t = 1.20;
screen_hole_dx = 37.72;
screen_hole_dy = 65.30;
screen_hole_d = 2.10;

// 可视窗口。略大于 VA 区，避免打印边框遮挡像素。
screen_va_w = 37.42;
screen_va_h = 49.66;
screen_window_w = screen_va_w + 1.60;
screen_window_h = screen_va_h + 2.20;
screen_window_y_offset = -3.00;     // 如果屏幕有效显示区偏移，可微调此值
screen_window_r = 1.20;

// 前壳上的屏幕螺丝柱。屏幕从后方用螺丝固定到这些柱子上。
screen_boss_od = 4.70;
screen_boss_h = 3.00;
screen_boss_pilot_d = 1.55;         // M2 自攻螺丝底孔；如需通孔可改为 2.20

// 简单实心屏幕 PCB 定位边，不做细小装饰槽。
screen_lip_t = 1.20;
screen_lip_h = screen_boss_h + 1.10;

// ---------- 外壳尺寸 ----------
// 尺寸尽量贴近屏幕 PCB，减少正面边框宽度。
body_w = 47.20;
body_h = 76.20;
shell_depth = 18.00;       // 足够容纳屏幕 PCB、走线以及固定在后盖上的 Pico

// ---------- 下沉式粘合后盖 ----------
cover_t = 2.20;

// 后盖搭接台阶/企口结构：
// 前壳后沿削薄到约 1/2 壁厚。
// 后盖落在更大的后部凹台内，而不是只塞进完整内腔。
// 这样可以避免卡扣/螺丝，并保持可见边框较窄。
rear_edge_wall = wall / 2;        // 外壳后沿削薄后的剩余边缘厚度
rear_rebate_depth = cover_t;      // 后盖落座台阶深度，通常等于后盖厚度

inner_w = body_w - 2*wall;
inner_h = body_h - 2*wall;
rear_rebate_w = body_w - 2*rear_edge_wall;
rear_rebate_h = body_h - 2*rear_edge_wall;
cover_w = rear_rebate_w - cover_clearance;
cover_h = rear_rebate_h - cover_clearance;

// ---------- 弧形定位凸包 / 封闭浅弧凹窝 ----------
// 无导槽入口：仅在后盖边缘做微小弧形凸包，并在前壳后唇做封闭弧形凹窝。
// 当 cover_clearance = 0.40 时，理论单边间隙约为 0.20 mm。
// detent_bead_out = 0.20 mm 时大致匹配该间隙，应表现为轻定位，而不是硬压配。
// 想更松/无卡感可用 0.16~0.18；想有轻微卡入感可用 0.22~0.25。
enable_arc_detents = true;
detent_bead_out = 0.45;          // 超出后盖边缘的凸出量；本模型中想尽量少变形建议 <= 0.20
detent_bead_r = 0.42;            // 圆柱半径；大于凸出量，外露部分会更平滑呈弧形
detent_bead_len = 5.00;          // 每个凸包沿边缘方向的长度
detent_pocket_depth = 0.34;      // 前壳后唇封闭浅弧凹窝深度
detent_pocket_extra = 1.20;      // 凹窝略长于凸包，便于对位
detent_pocket_r_extra = 0.08;    // 凹窝半径相对凸包半径的余量
detent_side_overlap = 0.04;      // 与台阶腔体微小重叠，避免共面渲染问题

// 每条长边上两个凸包的位置，用后盖高度比例表示。
detent_long_y_frac = 0.24;

// 每条短边中间 1 个凸包；如果只想保留长边两对凸包，可设为 false。
enable_short_edge_detents = true;

// ---------- Raspberry Pi Pico RP2040 USB-C，来自你的 Pico 图纸 ----------
pico_pcb_w = 21.00;
pico_pcb_h = 51.00;
pico_pcb_t = 1.30;
pico_hole_dx = 11.50;
pico_hole_dy = 47.00;       // 建议按你的 Pico 实物复测
pico_hole_d = 2.10;

// Pico 在后盖上的放置位置。
// USB-C 所在侧由 pico_usb_side_y 控制。
// 1  = Type-C 位于 Y 正方向短边 / 本版本的对侧
// -1 = Type-C 位于原始 Y 负方向短边
// 注意：
// Type-C 开孔应始终由后盖上的 Pico 位置推导。
// 不要单独调整外壳开孔，否则 Pico 固定到后盖后接口可能无法对准。
pico_usb_edge_inset = 1.10;
pico_usb_side_y = 1;  // 1 = Type-C 移到对侧，-1 = 原始侧
pico_usb_edge_y = pico_usb_side_y * (body_h/2 - wall - pico_usb_edge_inset);
pico_center_y = pico_usb_edge_y - pico_usb_side_y * pico_pcb_h/2;
pico_center_x = 0;

// 后盖上的 Pico 尾部螺丝柱。
pico_standoff_od = 5.00;
pico_standoff_h = 3.20;
pico_standoff_pilot_d = 1.55;       // M2 自攻螺丝底孔

// Pico USB 侧附近的宽支撑垫，用于防止 USB 侧悬空。
// 这里故意做成实心垫，而不是细薄导轨。
enable_pico_usb_support_pad = true;
pico_usb_pad_w = 18.00;
pico_usb_pad_h = 5.50;
pico_usb_pad_z = pico_standoff_h;

// ---------- USB-C 开孔 ----------
// 圆角 Type-C 形侧面开孔，不是方孔。
// 开孔位置根据固定在后盖上的 Pico 位置计算，
// 因此修改 cover_t / pico_standoff_h / pico_usb_edge_inset 时，开孔会同步移动。
typec_open_w = 9.40;
typec_open_h = 3.80;
typec_open_r = typec_open_h/2 - 0.05;
typec_cut_depth = wall + 4.50;

// Type-C 连接器口相对 Pico PCB USB 侧边缘的位置。
// 正值表示连接器口超过 Pico PCB USB 侧边缘，并朝选定短边方向外伸。
typec_mouth_from_pico_usb_edge = 1.20;

// Pico 安装在下沉后盖上时，连接器中心的 Z 位置。
// 如果试打后插头视觉上偏高/偏低，只调这个值。
// 该值越大，外壳开孔越靠近前面/屏幕侧，因为 Pico 元件面朝内。
typec_center_from_pcb_front = 1.70;

// 最终装配中的 Pico / Type-C 派生坐标。
// Pico PCB 固定在后盖螺柱朝前的一侧。
pico_mount_face_z = shell_depth - cover_t - pico_standoff_h;
pico_board_front_z = pico_mount_face_z - pico_pcb_t;
pico_board_center_z = pico_board_front_z + pico_pcb_t/2;

// 开孔中心跟随后盖固定 Pico 后的真实 Type-C 连接器中心。
typec_open_x = pico_center_x;
typec_open_y = pico_usb_edge_y + pico_usb_side_y * typec_mouth_from_pico_usb_edge;
typec_open_center_z = pico_board_front_z - typec_center_from_pcb_front;

// ---------- 后盖 3 按键 / 12x12 微动开关模块 ----------
// 根据你提供的图纸：
// - 12x12x7.3 高度直插四脚微动开关。
// - 圆形键帽外径约 φ12.8。
// 3 个按键放在后盖下方短边区域，避开 Pico USB 侧。
enable_rear_buttons = true;

// 后盖键帽开孔，默认使用 φ12.8 + 0.4 间隙。
// 如果只想让较小的键帽裙边穿过，可改成约 10.20。
button_keycap_hole_d = 13.20;
button_keycap_hole_clearance_z = 0.24;

// 后盖上 3 个按键中心位置，参数化便于后续微调。
button_center_x = 0.00;
button_center_y = -25.20;
button_pitch_x = 14.50;

// 每个孔周围的 12x12 微动开关本体限位框。
button_switch_body_w = 12.60;
button_switch_body_h = 12.60;
button_switch_fit_clearance = 0.30;
button_switch_limit_t = 0.70;
button_switch_limit_h = 1.20;       // 按键限位高度
button_switch_h = 7.30;             // 12x12x7.3 高度微动开关本体高度

// 用于固定独立按键压板/盖板的 2 个螺柱。
// 按你的要求：螺柱高度 = 开关限位高度 + 开关本体高度。
button_post_h = button_switch_limit_h + button_switch_h;
button_post_od = 4.40;
button_post_pilot_d = 1.55;         // M2 自攻螺丝底孔
button_plate_screw_clearance_d = 2.20;
button_plate_screw_x = 17.80;
button_plate_screw_rel_y = 10.20;
button_post_y = button_center_y + button_plate_screw_rel_y;

// 独立按键压板/盖板，每个微动开关背面对应 4 个小孔。
button_plate_w = 44.00;
button_plate_h = 23.20;
button_plate_t = 1.40;
button_plate_r = 1.80;
button_pin_dx = 10.00;              // 四脚微动开关引脚间距，X 方向；需要时按实物微调
button_pin_dy = 5.00;               // 四脚微动开关引脚间距，Y 方向；需要时按实物微调
button_pin_hole_d = 1.40;
button_pin_relief_d = 3.20;         // 中心小避让孔，用于避让开关背面凸点/焊点鼓包


// ---------- 辅助模块 ----------
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

// 选定短边侧壁上的圆角接口切孔。截面在 X-Z 平面，拉伸方向为 Y。
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
  // 尾部孔位于 USB-C 接口的相反一端。
  for (x = [-pico_hole_dx/2, pico_hole_dx/2])
    translate([pico_center_x + x, pico_center_y - pico_usb_side_y * pico_hole_dy/2, 0]) children();
}


module at_button_positions() {
  if (enable_rear_buttons)
    for (x = [-button_pitch_x, 0, button_pitch_x])
      translate([button_center_x + x, button_center_y, 0]) children();
}

module at_button_plate_button_positions() {
  if (enable_rear_buttons)
    for (x = [-button_pitch_x, 0, button_pitch_x])
      translate([x, 0, 0]) children();
}

module at_button_post_positions() {
  if (enable_rear_buttons)
    for (sx = [-1, 1])
      translate([sx * button_plate_screw_x, button_post_y, 0]) children();
}

module at_button_plate_screw_positions() {
  if (enable_rear_buttons)
    for (sx = [-1, 1])
      translate([sx * button_plate_screw_x, button_plate_screw_rel_y, 0]) children();
}

module at_button_switch_pins() {
  for (px = [-button_pin_dx/2, button_pin_dx/2])
    for (py = [-button_pin_dy/2, button_pin_dy/2])
      translate([px, py, 0]) children();
}

module rear_button_keycap_hole_cuts() {
  at_button_positions()
    translate([0, 0, -button_keycap_hole_clearance_z/2])
      cylinder(d = button_keycap_hole_d,
               h = cover_t + button_keycap_hole_clearance_z);
}

module tactile_switch_locator_one() {
  // 12x12 微动开关周围的低矮限位筋；只限制 XY 位移，不做紧压配。
  inner_w = button_switch_body_w + 2*button_switch_fit_clearance;
  inner_h = button_switch_body_h + 2*button_switch_fit_clearance;
  t = button_switch_limit_t;
  h = button_switch_limit_h;

  // 左/右限位筋。
  add_box(t, inner_h + 2*t, h, -inner_w/2 - t/2, 0, cover_t);
  add_box(t, inner_h + 2*t, h,  inner_w/2 + t/2, 0, cover_t);

  // 上/下限位筋。如果与圆形键帽孔重叠，会被孔轻微切开，
  // 这是可以接受的，因为它们只起定位限位作用。
  add_box(inner_w, t, h, 0, -inner_h/2 - t/2, cover_t);
  add_box(inner_w, t, h, 0,  inner_h/2 + t/2, cover_t);
}

module rear_button_switch_locators() {
  at_button_positions()
    tactile_switch_locator_one();
}

module button_plate_raw() {
  difference() {
    rounded_prism(button_plate_w, button_plate_h, button_plate_t, button_plate_r);

    // 对应后盖 2 个螺柱的 M2 过孔。
    at_button_plate_screw_positions()
      translate([0, 0, -0.30])
        cylinder(d = button_plate_screw_clearance_d, h = button_plate_t + 0.60);

    // 每个微动开关背面 4 个引脚对应的小孔。
    at_button_plate_button_positions() {
      at_button_switch_pins()
        translate([0, 0, -0.30])
          cylinder(d = button_pin_hole_d, h = button_plate_t + 0.60);

      // 额外中间避让孔，用于避让开关背面的塑料凸点或焊点鼓包。
      translate([0, 0, -0.30])
        cylinder(d = button_pin_relief_d, h = button_plate_t + 0.60);
    }
  }
}

module button_cover_plate() {
  // 整体 XY 位置与后盖 3 个按键孔对应。
  translate([button_center_x, button_center_y, 0])
    button_plate_raw();
}



module arc_bead_long_side(sx, y) {
  // 后盖长边上的微小圆柱形凸包。
  // 圆柱大部分埋入后盖板内，仅 detent_bead_out 部分外露。
  bead_x = sx * (cover_w/2 + detent_bead_out - detent_bead_r);
  translate([bead_x, y, cover_t/2])
    rotate([90, 0, 0])
      cylinder(r = detent_bead_r, h = detent_bead_len, center = true);
}

module arc_bead_short_side(sy, x) {
  // 后盖短边上的微小圆柱形凸包。
  bead_y = sy * (cover_h/2 + detent_bead_out - detent_bead_r);
  translate([x, bead_y, cover_t/2])
    rotate([0, 90, 0])
      cylinder(r = detent_bead_r, h = detent_bead_len, center = true);
}

module rear_cover_arc_detents() {
  if (enable_arc_detents) {
    // 长边：每侧 2 个凸包。
    for (sx = [-1, 1])
      for (yf = [-detent_long_y_frac, detent_long_y_frac])
        arc_bead_long_side(sx, yf * cover_h);

    // 短边：每侧中间 1 个凸包。
    if (enable_short_edge_detents)
      for (sy = [-1, 1])
        arc_bead_short_side(sy, 0);
  }
}



module arc_scoop_long_side(sx, y) {
  // 前壳后部台阶壁上的匹配浅弧凹窝。
  // 中心 Z 与后盖翻入外壳后的凸包装配位置一致。
  pocket_r = detent_bead_r + detent_pocket_r_extra;
  pocket_len = detent_bead_len + detent_pocket_extra;
  pocket_center_x = sx * (rear_rebate_w/2 + detent_pocket_depth - pocket_r - detent_side_overlap);
  pocket_center_z = shell_depth - cover_t/2;
  translate([pocket_center_x, y, pocket_center_z])
    rotate([90, 0, 0])
      cylinder(r = pocket_r, h = pocket_len, center = true);
}

module arc_scoop_short_side(sy, x) {
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
    // 长边：每侧 2 个封闭弧形凹窝。
    for (sx = [-1, 1])
      for (yf = [-detent_long_y_frac, detent_long_y_frac])
        arc_scoop_long_side(sx, yf * cover_h);

    // 短边：每侧中间 1 个封闭弧形凹窝。
    if (enable_short_edge_detents)
      for (sy = [-1, 1])
        arc_scoop_short_side(sy, 0);
  }
}

// ---------- 前壳 ----------
module screen_locator_lips() {
  // 宽定位边，结构简单，方便打印。
  x_lip = screen_pcb_w/2 + fit_clearance/2 + screen_lip_t/2;
  y_lip = screen_pcb_h/2 + fit_clearance/2 + screen_lip_t/2;

  // 左/右定位边
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
          -x_lip, 0, front_thick);
  add_box(screen_lip_t, screen_pcb_h + 2*screen_lip_t, screen_lip_h,
           x_lip, 0, front_thick);

  // 下定位边。上定位边分成两段，给屏幕排针/线材留更多空间。
  add_box(screen_pcb_w + 2*screen_lip_t, screen_lip_t, screen_lip_h,
          0, -y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
          -(screen_pcb_w/4 + 1.50), y_lip, front_thick);
  add_box(screen_pcb_w/2 - 3.00, screen_lip_t, screen_lip_h,
           (screen_pcb_w/4 + 1.50), y_lip, front_thick);
}

module rear_rabbet_cut() {
  // 后沿切口比主内腔更大。
  // 这样形成半壁厚台阶，使后盖可以落入外壳。
  // 该切口底部就是后盖落座台阶。
  translate([0, 0, shell_depth - rear_rebate_depth])
    rounded_prism(rear_rebate_w, rear_rebate_h,
                  rear_rebate_depth + 0.80,
                  max(0.10, corner_r - rear_edge_wall));
}

module front_shell() {
  difference() {
    union() {
      difference() {
        // 外壳外形。
        rounded_prism(body_w, body_h, shell_depth, corner_r);

        // 后部主空腔；保留前面板和完整侧壁。
        translate([0, 0, front_thick])
          rounded_prism(inner_w, inner_h,
                        shell_depth - front_thick + 0.80,
                        max(0.10, corner_r - wall));

        // 粘合后盖用的后部半壁厚台阶。
        // 这就是实际的“后沿削薄到 1/2 壁厚”结构。
        rear_rabbet_cut();

        // 正面屏幕窗口。
        rounded_cut(screen_window_w, screen_window_h,
                    front_thick + 1.20, screen_window_r,
                    0, screen_window_y_offset, -0.60);
      }

      // 4 个 M2 屏幕螺丝柱。
      at_screen_holes()
        translate([0, 0, front_thick])
          cylinder(d = screen_boss_od, h = screen_boss_h);

      // 简单屏幕 PCB 定位槽。
      screen_locator_lips();

    }

    // Type-C 侧面开孔；如与内部台阶重叠，会一起切穿。
    side_typec_cut(typec_open_w, typec_open_h, typec_cut_depth, typec_open_r,
                   typec_open_x, typec_open_y, typec_open_center_z);

    // 后盖定位凸包对应的封闭浅弧凹窝。
    front_shell_arc_scoop_cuts();

    // 屏幕 M2 螺丝底孔。
    at_screen_holes()
      translate([0, 0, front_thick - 0.30])
        cylinder(d = screen_boss_pilot_d, h = screen_boss_h + 0.80);
  }
}

// ---------- 后盖，含 Pico 尾部固定结构，粘合式 ----------
module back_cover() {
  difference() {
    union() {
      // 后盖板。落入半壁厚后部台阶，并沿边缘点胶固定。
      rounded_prism(cover_w, cover_h, cover_t, max(0.10, corner_r - rear_edge_wall - cover_clearance/2));

      // 微小弧形定位凸包，与前壳封闭浅弧凹窝匹配。
      rear_cover_arc_detents();

      // 后盖内侧的 2 个 Pico 尾部螺柱。
      at_pico_tail_holes()
        translate([0, 0, cover_t])
          cylinder(d = pico_standoff_od, h = pico_standoff_h);

      // Pico USB 侧宽支撑垫，实心且易打印。
      if (enable_pico_usb_support_pad)
        add_box(pico_usb_pad_w, pico_usb_pad_h, pico_usb_pad_z,
                pico_center_x, pico_usb_edge_y - pico_usb_side_y * (pico_usb_pad_h/2 + 2.00),
                cover_t);

      // 后盖 3 个按键孔周围的微动开关 XY 限位筋。
      rear_button_switch_locators();

      // 用于独立按键压板/盖板的 2 个螺柱。
      at_button_post_positions()
        translate([0, 0, cover_t])
          cylinder(d = button_post_od, h = button_post_h);
    }

    // 后盖上 3 个圆形键帽通孔。
    rear_button_keycap_hole_cuts();

    // 2 个 Pico 尾部螺柱中的 M2 底孔。
    at_pico_tail_holes()
      translate([0, 0, cover_t - 0.20])
        cylinder(d = pico_standoff_pilot_d, h = pico_standoff_h + 0.60);

    // 2 个按键盖板螺柱中的 M2 底孔。
    at_button_post_positions()
      translate([0, 0, cover_t - 0.20])
        cylinder(d = button_post_pilot_d, h = button_post_h + 0.60);
  }
}


// ---------- 同平面 3D 打印排版 ----------
module print_plate() {
  // 所有可打印零件都放在同一 Z=0 平面。
  // 左侧：front_shell，屏幕/正面贴床。
  // 中间：back_cover，后盖外表面贴床，Pico/按键螺柱朝上。
  // 右侧：独立的薄按键压板/盖板。
  translate([-(body_w/2 + plate_gap + cover_w/2), 0, 0])
    front_shell();

  translate([0, 0, 0])
    back_cover();

  translate([(cover_w/2 + plate_gap + button_plate_w/2), 0, 0])
    button_plate_raw();
}

// ---------- 预览参考件 ----------
module screen_reference() {
  // 近似屏幕 PCB 外形；显示面朝前。
  color([0.0, 0.7, 0.1, 0.25])
    translate([0, 0, front_thick + screen_boss_h + screen_pcb_t/2])
      cube([screen_pcb_w, screen_pcb_h, screen_pcb_t], center = true);

  // 有效显示窗口参考。
  color([0.0, 0.0, 0.0, 0.35])
    translate([0, screen_window_y_offset, 0.15])
      cube([screen_window_w, screen_window_h, 0.30], center = true);
}

module pico_reference() {
  color([0.05, 0.20, 0.90, 0.28])
    translate([pico_center_x, pico_center_y, pico_board_center_z])
      cube([pico_pcb_w, pico_pcb_h, pico_pcb_t], center = true);

  // USB 侧 Type-C 连接器粗略外形。
  color([1.0, 0.45, 0.10, 0.55])
    translate([typec_open_x, typec_open_y, typec_open_center_z])
      cube([9.00, 4.00, 3.20], center = true);
}

module assembled_back_cover() {
  // 旋转后盖，使其内侧结构朝向外壳内部。
  // 使用 Y 轴翻转而不是 X 轴翻转，使 Pico USB-C 侧保持在选定的 Y 侧，
  // 从而在装配后与前壳 Type-C 开孔对齐。
  // 外侧/后表面在 Z = shell_depth 处与外壳后端齐平。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      back_cover();
}

module assembled_button_cover_plate() {
  // 按键压板/盖板预览为前/上表面与螺柱顶部齐平。
  // 这样可避免新增盖板在现有 18 mm 外壳深度内与屏幕 PCB 干涉。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      translate([0, 0, cover_t + button_post_h - button_plate_t])
        button_cover_plate();
}

// ---------- 零件选择 ----------
if (part == "print_plate") {
  print_plate();
} else if (part == "front_shell") {
  front_shell();
} else if (part == "back_cover") {
  back_cover();
} else if (part == "button_plate") {
  button_plate_raw();
} else if (part == "exploded") {
  translate([0, 0, 0]) front_shell();
  translate([0, 0, 27]) back_cover();
  translate([0, 0, 42]) button_plate_raw();
  translate([0, 0, 0]) screen_reference();
} else {
  color([0.86, 0.86, 0.86, 1.0]) front_shell();
  color([0.70, 0.70, 0.70, 0.85]) assembled_back_cover();
  color([0.35, 0.35, 0.35, 0.70]) assembled_button_cover_plate();
  screen_reference();
  pico_reference();

  // Type-C 开孔参考。
  color([1.0, 0.20, 0.10, 0.45])
    side_typec_cut(typec_open_w, typec_open_h, 1.80, typec_open_r,
                   typec_open_x, typec_open_y, typec_open_center_z);
}
