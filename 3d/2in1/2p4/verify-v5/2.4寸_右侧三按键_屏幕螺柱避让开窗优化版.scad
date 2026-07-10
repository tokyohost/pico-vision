/*
  2.4寸 ST7789 240x320 IPS 屏幕 + Raspberry Pi Pico 外壳
  单位：mm

  本版按照新屏幕图纸重新调整：
    1. 屏幕 PCB：46.90±0.20 x 71.00±0.20 x 1.20mm；
    2. 四个屏幕孔中心距：37.70 x 65.80mm，孔径 φ2.10；
    3. VA 有效显示区：37.42 x 49.66mm；
    4. 外壳尺寸按 PCB 最大公差重新计算，避免 47.10 x 71.20mm 实物装不进去；
    5. 原后盖三按键结构已删除；
    6. 三枚 6x6x7.3 轻触开关改到右侧长边，沿 Y 方向纵向排列；
    7. 继续使用 φ8 外帽、φ5.6 导向套的配套键帽；
    8. 右侧壁开三个 φ6.10 导向孔，并增加内部加强筋、开关限位框；
    9. 使用两个横向 M2 盲孔螺柱和一块独立侧按键压板固定开关；
    10. Pico 四螺柱、两块小压盖、三个限位和 Type-C 结构保持不变；
    11. 侧按键横向圆柱螺柱改为方形承压座 + 45°自支撑斜撑；
    12. 横向 M2 圆底孔改为顶部尖角的水滴孔，减少横孔塌顶；
    13. 重新区分 PCB、金属外框、背光、可视框和 VA 五组尺寸；
    14. 正面开窗改为按 VA 计算的 38.10 x 50.10mm，不再使用过大的 39.02 x 51.86mm；
    15. 四个屏幕螺柱向前面板内嵌 0.60mm，消除共面悬空；
    16. 删除会侵入显示外框凹槽的 φ5.60 同心圆底座；
    17. 主螺柱缩为 φ4.00，并在 PCB 外缘方向增加偏心加固脚，避开显示凹槽。

  坐标方向：
    X = 屏幕宽度方向，+X 为右侧按键所在长边；
    Y = 屏幕高度方向；
    Z = 前面板外表面指向后盖。

  part 可选：
    "print_plate"：前壳、后盖、两块 Pico 小压盖和侧按键压板同板打印
    "front_shell"：只导出带右侧按键结构的前壳
    "back_cover"：只导出后盖
    "pico_pair_clamp_cover"：只导出一块 Pico 小压盖
    "side_button_plate"：只导出右侧三按键压板
    "button_plate"：兼容旧名称，同样导出右侧三按键压板
    "assembly"：装配预览
    "exploded"：爆炸预览
*/

$fn = 56;
part = "print_plate";    // 可选："print_plate", "front_shell", "back_cover", "pico_pair_clamp_cover", "side_button_plate", "button_plate", "typec_clamp_cover", "typec_fit_test", "assembly", "exploded"

// ---------- 打印与装配余量 ----------
wall = 1.80;               // 外壳侧壁厚度
front_thick = 2.00;        // 前面板厚度
corner_r = 3.20;           // 外壳圆角
fit_clearance = 0.70;      // 按 PCB ±0.20 公差设计；最大板装入后仍约有单边 0.15mm 余量
cover_clearance = 0.40;    // 后盖落入台阶的总余量，约等于单边 0.20
plate_gap = 12.00;         // 同板打印时两个零件之间的间距

// ---------- 新 2.4寸 IPS 屏幕模块：按图纸重新分层 ----------
// 1. PCB 外形。
screen_pcb_w = 46.90;
screen_pcb_h = 71.00;
screen_pcb_w_max = 47.10;   // 46.90 + 0.20
screen_pcb_h_max = 71.20;   // 71.00 + 0.20
screen_pcb_t = 1.20;

// 2. PCB 四个安装孔。
// 图纸上孔中心到上、下边均为 2.60mm，因此纵向中心距为 65.80mm。
screen_hole_dx = 37.70;
screen_hole_dy = 65.80;
screen_hole_d = 2.10;
screen_hole_edge_x = (screen_pcb_w - screen_hole_dx) / 2; // 4.60
screen_hole_edge_y = (screen_pcb_h - screen_hole_dy) / 2; // 2.60

// 3. 金属/塑料显示外框，图纸标注“壳”。
// 43.50 x 61.10mm；上下距 PCB 边均约 4.95mm，因此相对 PCB 居中。
screen_shell_w = 43.50;
screen_shell_h = 61.10;
screen_shell_top_from_pcb = 4.95;
screen_shell_y_offset =
    screen_pcb_h/2
    - (screen_shell_top_from_pcb + screen_shell_h/2); // 0.00

// 4. 背光组件 BL：42.72±0.15 x 58.80±0.15mm。
// 58.80mm 高度在 71mm PCB 上下各余 6.10mm，按图纸居中。
screen_bl_w = 42.72;
screen_bl_h = 58.80;
screen_bl_top_from_pcb = (screen_pcb_h - screen_bl_h) / 2; // 6.10
screen_bl_y_offset =
    screen_pcb_h/2
    - (screen_bl_top_from_pcb + screen_bl_h/2); // 0.00

// 5. 图纸中的可视框尺寸：37.90 x 49.80mm。
// 顶部相对外框再下移约 2.30mm。
screen_view_w = 37.90;
screen_view_h = 49.80;
screen_view_top_from_pcb =
    screen_shell_top_from_pcb + 2.30; // 7.25
screen_view_y_offset =
    screen_pcb_h/2
    - (screen_view_top_from_pcb + screen_view_h/2); // +3.35

// 6. VA 真正有效显示区：37.42 x 49.66mm。
// 图纸顶部相对外框下移约 2.65mm。
screen_aa_w = 37.42;
screen_aa_h = 49.66;
screen_aa_top_from_pcb =
    screen_shell_top_from_pcb + 2.65; // 7.60
screen_aa_y_offset =
    screen_pcb_h/2
    - (screen_aa_top_from_pcb + screen_aa_h/2); // +3.07

// 7. 前壳实际开窗。
// 以 VA 为中心，在宽、高方向分别增加 0.68mm 和 0.44mm 总余量。
// 这样不会像上一版 39.02 x 51.86mm 那样露出过多黑边。
screen_window_clearance_w = 0.68;
screen_window_clearance_h = 0.44;
screen_window_w = screen_aa_w + screen_window_clearance_w; // 38.10
screen_window_h = screen_aa_h + screen_window_clearance_h; // 50.10
screen_window_y_extra_tune = 0.00;
screen_window_y_offset =
    screen_aa_y_offset + screen_window_y_extra_tune;
screen_window_r = 1.00;

// 8. 前面板内侧避让槽按 43.50 x 61.10mm 外框设计，
// 每边再增加 0.30mm 装配余量。
screen_shell_relief_clearance = 0.40;
screen_bl_relief_w =
    screen_shell_w + screen_shell_relief_clearance; // 43.90
screen_bl_relief_h =
    screen_shell_h + screen_shell_relief_clearance; // 61.50
screen_bl_relief_y_offset = screen_shell_y_offset;
screen_bl_relief_depth = 0.80;
screen_bl_relief_r = 1.20;

// 9. 屏幕 M2 螺柱。
// 关键修复：螺柱和定位边不能从 front_thick 恰好开始，
// 否则只是共面接触，可能在 STL 中成为悬空独立网格。
// 安装孔中心距与显示外框在 Y 方向非常接近：
//   孔中心 |Y| = 32.90mm
//   显示外框凹槽半高 = 30.75mm
// 因此同心圆螺柱最大半径只能接近 2.15mm。
// 主螺柱采用 φ4.00，给凹槽保留约 0.15mm 理论间隙。
screen_boss_od = 4.00;
screen_support_h = 3.00;
screen_boss_h = screen_support_h;
screen_boss_embed = 0.60;       // 向前面板实体内嵌
screen_boss_pilot_d = 1.55;
screen_pilot_bottom_skin = 0.20;
screen_thread_depth_actual = screen_support_h;

// 不再使用会向屏幕中心扩张的同心圆底座。
// 改为向 PCB 上、下外缘偏移的加固脚，增加根部面积但不侵入显示凹槽。
screen_boss_anchor_od = 5.60;
screen_boss_anchor_shift_y = 1.60;
screen_boss_anchor_h = 1.00;
screen_boss_anchor_embed = screen_boss_embed;

// 几何安全距离。
screen_relief_half_h = screen_bl_relief_h / 2;
screen_boss_inward_gap =
    screen_hole_dy/2 - screen_boss_od/2 - screen_relief_half_h;
screen_anchor_inward_gap =
    screen_hole_dy/2 + screen_boss_anchor_shift_y
    - screen_boss_anchor_od/2 - screen_relief_half_h;

// 10. 屏幕 PCB 四周定位边也向前面板内嵌，避免共面悬空。
screen_lip_t = 1.20;
screen_lip_h = screen_support_h + 1.10;
screen_lip_embed = 0.40;

// ---------- 根据新 PCB 最大公差计算外壳 ----------
body_side_margin = 2.45;
body_top_bottom_margin = 3.00;
body_w = screen_pcb_w_max + 2*body_side_margin;       // 52.00
body_h = screen_pcb_h_max + 2*body_top_bottom_margin; // 77.20
shell_depth = 18.00;

// 屏幕定位槽真实尺寸和最大 PCB 余量。
screen_locator_w = screen_pcb_w + fit_clearance;
screen_locator_h = screen_pcb_h + fit_clearance;
screen_max_clearance_x =
    (screen_locator_w - screen_pcb_w_max) / 2;
screen_max_clearance_y =
    (screen_locator_h - screen_pcb_h_max) / 2;

echo(str("校验：PCB=", screen_pcb_w, " x ", screen_pcb_h,
         "mm；最大=", screen_pcb_w_max, " x ", screen_pcb_h_max, "mm"));
echo(str("校验：孔距=", screen_hole_dx, " x ", screen_hole_dy,
         "mm；孔边距=", screen_hole_edge_x, " / ",
         screen_hole_edge_y, "mm"));
echo(str("校验：外框=", screen_shell_w, " x ", screen_shell_h,
         "mm；BL=", screen_bl_w, " x ", screen_bl_h, "mm"));
echo(str("校验：可视框=", screen_view_w, " x ", screen_view_h,
         "mm，Y=", screen_view_y_offset,
         "；VA=", screen_aa_w, " x ", screen_aa_h,
         "mm，Y=", screen_aa_y_offset));
echo(str("校验：前壳开窗=", screen_window_w, " x ",
         screen_window_h, "mm，Y=", screen_window_y_offset));
echo(str("校验：定位槽=", screen_locator_w, " x ",
         screen_locator_h, "mm；最大PCB单边余量X=",
         screen_max_clearance_x, "，Y=", screen_max_clearance_y, "mm"));
echo(str("校验：屏幕主螺柱=φ", screen_boss_od,
         "mm；内嵌=", screen_boss_embed,
         "mm；主柱到显示凹槽理论间隙=",
         screen_boss_inward_gap, "mm"));
echo(str("校验：屏幕螺柱偏心加固脚=φ",
         screen_boss_anchor_od, "mm；向PCB外缘偏移=",
         screen_boss_anchor_shift_y,
         "mm；加固脚到显示凹槽理论间隙=",
         screen_anchor_inward_gap, "mm"));
echo(str("校验：外壳=", body_w, " x ", body_h,
         " x ", shell_depth, "mm"));

assert(screen_boss_inward_gap > 0,
       "错误：屏幕主螺柱侵入显示外框凹槽，请减小 screen_boss_od");
assert(screen_anchor_inward_gap > 0,
       "错误：屏幕螺柱加固脚侵入显示外框凹槽，请增大外移距离");

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

// ---------- 新 Pico：以 Type-C 口为基准定位 ----------
// 你的 Pico PCB 尺寸：53.00 x 20.50 x 1.10mm。这里约定：X=板宽 20.50mm，Y=板长 53.00mm。
// 关键改动：Pico 不再靠板长或尾部孔位决定 USB 位置，而是外壳 Type-C 开孔固定，Pico 的 Type-C 连接器插入限位座后被压盖锁死。
pico_pcb_w = 20.55;
pico_pcb_h = 53.00;
pico_pcb_t = 1.10;

// Pico 固定高度基准。旧版双尾孔螺柱已经彻底删除。
pico_standoff_h = 3.20;    // 同时作为 Pico PCB 支撑高度基准

// Pico 板身辅助支撑：只托 PCB 边缘/USB 后方，不参与 Type-C 精定位。
// 如果板背面有元件顶到支撑，可以先把 enable_pico_board_support_rails 或 enable_pico_usb_support_pad 改成 false。
enable_pico_board_support_rails = true;
pico_rail_w = 1.50;
pico_rail_h = 28.00;
pico_rail_x_offset = pico_pcb_w/2 - 1.80;
pico_rail_y = 2.00;

enable_pico_usb_support_pad = true;
pico_usb_pad_w = 14.00;
pico_usb_pad_h = 4.00;
pico_usb_pad_z = pico_standoff_h - 0.10;

// Pico Type-C 在外壳哪条短边：1 = +Y 短边；-1 = -Y 短边/对向侧。
pico_usb_side_y = -1;
pico_center_x = 0;  // Pico 与 Type-C 开孔在 X 方向居中

// ---------- Type-C 开孔：外壳开孔位置固定，不再由 Pico 板长反推 ----------
typec_open_w = 9.40;       // 外壳 Type-C 开孔宽；常见 USB-C 母座建议 9.2~9.8mm
typec_open_h = 3.80;       // 外壳 Type-C 开孔高；常见 USB-C 母座建议 3.6~4.0mm
typec_open_r = typec_open_h/2 - 0.05;
typec_cut_depth = wall + 5.20;

// 开孔中心放在外壳短边侧壁厚度中心线上。
typec_open_y = pico_usb_side_y * (body_h/2 - wall/2);
typec_open_x = 0;

// 新 Pico 的 Type-C 口“不突出”：连接器口面基本与 PCB USB 端板边齐平。
// 为避免 PCB 端边顶进前壳侧壁，板边退到内壁后方一点点。
typec_connector_front_from_pcb_edge = 0.00;
typec_pcb_edge_clearance_from_inner_wall = 0.35;
pico_usb_edge_y = pico_usb_side_y * (body_h/2 - wall - typec_pcb_edge_clearance_from_inner_wall);
typec_connector_mouth_y = pico_usb_edge_y + pico_usb_side_y * typec_connector_front_from_pcb_edge;
pico_center_y = pico_usb_edge_y - pico_usb_side_y * pico_pcb_h/2;

// 根据后盖扣合后的真实位置重新推导 Type-C 开孔中心高度。
// 按你的要求：前壳 Type-C 开孔保留上一版改动，按“后盖扣上后 + PCB 厚 1.10mm”计算。
// 前壳坐标里 Z 从正面往后盖方向增大，所以从后盖内表面往前壳方向要做减法。
typec_shell_h_for_open_calc = 3.00;
typec_pcb_back_gap_from_cover_inner = 0.00;  // PCB 平整背面到后盖内表面的理论间隙；需要垫高可改这里
typec_open_z_extra_tune = -1.00;            // Type-C 开孔高度微调；正数往后盖方向，负数往前壳方向；本版按要求往前壳方向移动 1mm
pico_board_back_z = shell_depth - cover_t - typec_pcb_back_gap_from_cover_inner;
pico_board_front_z = pico_board_back_z - pico_pcb_t;
pico_board_center_z = pico_board_back_z - pico_pcb_t/2;
typec_open_center_z = pico_board_front_z - typec_shell_h_for_open_calc/2 + typec_open_z_extra_tune;

// 只用于校验输出和旧模块兼容：PCB 背面到 Type-C 外侧最高点的理论值。
typec_stack_h_from_pcb_back = pico_pcb_t + typec_shell_h_for_open_calc;
typec_center_from_pcb_front = typec_shell_h_for_open_calc/2;

// ---------- Type-C 连接器限位座 + 独立压盖 ----------
// 这一版按 FDM / 树脂打印的实际误差重新做了 Type-C 限位：
//   1. 不做整条硬夹槽，改成“入口导向 + 短定位点 + 后挡块 + 压盖防脱”。
//   2. 关键定位只在少量短凸台上完成，避免长边摩擦导致插不进去。
//   3. 压盖默认 0.05mm 理论间隙，FDM 实际接近贴合压紧；需要更紧可改成 0 或 -0.05。
//   4. 墙厚、螺丝孔、导向间隙按 0.4mm 喷嘴和 0.2mm 层高做了保守处理。
enable_typec_locator_lock = true;

// 打印补偿：FDM 常见 XY 误差、孔会偏小，优先通过这里调。
typec_fdm_xy_clearance = 0.28;        // 普通 FDM 建议 0.25~0.35；树脂可降到 0.15~0.22
typec_final_side_clearance = 0.20;    // 最终定位点单边间隙；太紧就加到 0.25~0.28
typec_guide_side_clearance = 0.65;    // 入口导向单边间隙；故意做大，方便装配
typec_z_clearance = 0.25;             // Z 向余量；按 4.50mm 组合高度预留，避免层纹把 Type-C 顶住
typec_min_print_wall = 1.45;          // 小结构最小墙厚；0.4 喷嘴建议 >= 1.2，本版取 1.45 更稳

// Type-C 母座金属壳/本体实测尺寸。
// 如果你的母座实测不是这个尺寸，只需要改下面 3 个值，外壳开孔和限位座会一起跟着校准。
typec_shell_w = 9.00;      // Type-C 母座金属壳宽度，沿 X
typec_shell_d = 7.00;      // Type-C 母座本体深度，沿 Y，从口面向板内
typec_shell_h = 3.00;      // Type-C 母座高度，沿 Z

// 保留旧变量名，避免后续模块引用出错；新结构实际使用 final/guide/z 三种余量。
typec_shell_clearance = typec_fdm_xy_clearance;
typec_locator_wall_t = typec_min_print_wall;
typec_locator_extra_y = 0.80;

pico_mount_boss_shift_to_stop = 5.00;
pico_mount_boss_shift_y = -pico_usb_side_y * pico_mount_boss_shift_to_stop;
pico_mount_boss_shift_x = 0.00;  // 已把 Pico 中心校正到 X=0，无需再次偏移



// 精细限位参数。
typec_locator_point_len = 2.40;       // 短定位点长度；越短越不怕打印误差
typec_locator_front_relief = 1.20;    // 靠近外壳开孔处留空，不在口面附近硬夹
typec_lead_in_len = 3.00;             // 入口导向长度
typec_stop_wall_t = 1.60;             // 后挡块厚度，限制插拔方向回退
typec_bottom_pad_w = 2.20;            // 底部托点宽度，左右各一个，避免大面积顶到元件
typec_bottom_pad_len = 4.80;
typec_bottom_pad_h = 0.90;

// Type-C 本体中心：由口面位置反推，不依赖 Pico 板长。
typec_shell_center_y = typec_connector_mouth_y - pico_usb_side_y * (typec_shell_d/2);
typec_shell_center_z_on_cover = shell_depth - typec_open_center_z;
typec_shell_local_z0 = typec_shell_center_z_on_cover - (typec_shell_h + 2*typec_z_clearance)/2;
typec_locator_h = typec_shell_h + 2*typec_z_clearance;

// 压盖用两个 M2 螺丝固定到后盖上的高螺丝柱，锁住 Type-C 连接器后，Pico 板长差异只影响尾部位置，不影响接口对齐。
typec_clamp_screw_dx = 16.00;
typec_clamp_screw_y = typec_shell_center_y;
typec_clamp_boss_od = 5.20;
typec_clamp_boss_pilot_d = 1.60;       // M2 自攻底孔；FDM 孔会偏小，1.55~1.70 都可试
typec_clamp_screw_clear_d = 2.40;      // 压盖 M2 通孔；FDM 建议 2.35~2.50
typec_clamp_screw_head_d = 4.40;       // M2 螺丝头沉孔/避让
typec_clamp_screw_head_depth = 0.80;
typec_clamp_cover_t = 1.80;
typec_clamp_cover_w = typec_clamp_screw_dx + typec_clamp_boss_od + 3.00;
typec_clamp_cover_h = typec_shell_d + 4.20;
typec_clamp_cover_r = 1.00;
typec_clamp_limit_gap = 0.05;          // 压盖与 Type-C 的理论间隙；FDM 实际通常接近轻微压紧，想更紧可改 0 或 -0.05
typec_clamp_stiffener_h = 0.80;
typec_clamp_stiffener_w = typec_shell_w + 2.00;
typec_clamp_stiffener_y = -pico_usb_side_y * (typec_clamp_cover_h/2 - 1.50);
typec_clamp_cover_local_z0 = typec_shell_center_z_on_cover + typec_shell_h/2 + typec_clamp_limit_gap;
typec_clamp_boss_h = typec_clamp_cover_local_z0 - cover_t;

// OpenSCAD 控制台校验输出。
echo(str("校验：新 Pico PCB=", pico_pcb_h, " x ", pico_pcb_w, " x ", pico_pcb_t, "mm；定位基准=Type-C 连接器，不再依赖板长"));
echo(str("校验：Type-C 外壳开孔中心 Y=", typec_open_y, "mm；Pico USB 端板边 Y=", pico_usb_edge_y, "mm；Type-C 口面 Y=", typec_connector_mouth_y, "mm"));
echo(str("校验：Type-C 开孔中心Z=", typec_open_center_z, "mm；后盖内表面Z=", shell_depth - cover_t, "mm；PCB元件面Z=", pico_board_front_z, "mm；计算方式=后盖扣上后 + PCB厚 ", pico_pcb_t, "mm + Type-C半高 ", typec_shell_h_for_open_calc/2, "mm"));
echo(str("校验：Type-C 限位座本体=", typec_shell_w, " x ", typec_shell_d, " x ", typec_shell_h, "mm；PCB+Type-C理论总高=", typec_stack_h_from_pcb_back, "mm；压盖螺丝中心距=", typec_clamp_screw_dx, "mm"));

// ---------- 后盖 PCB 固定结构：参考你给的 SVG 草图 ----------
// 设计思路：
//   1. PCB 元件主要在 Type-C 那一面，背面基本全平，所以后盖只托住 PCB 平整背面。
//   2. 草图里的 4 个圆孔按 M2 螺柱处理，用螺丝固定 PCB，不再当普通支撑垫。
//   3. 非 Type-C 一端不再用两条很近的竖向挡板，改成一条与短边平行的横向挡板。
//   4. 左右两组螺柱中心距加大到 26mm，螺丝孔避开 20.50mm 宽的 PCB，避免被 PCB 压住。
//   5. 整个固定结构都只接触 PCB 平整背面和板边，不去压 Type-C 那一面的电子元件。
//   6. 后盖四周原有的弧形小凸点卡扣继续保留，用于和前壳浅凹窝过盈定位。
enable_pico_svg_mount = true;

// 4 个圆形 M2 螺柱。
pico_back_support_h = pico_standoff_h;   // 螺柱高度继续沿用现有 Type-C 高度基准，保证接口高度不变
pico_mount_boss_od = 5.20;              // M2 螺柱外径，草图中的圆孔位置就是这些螺柱
pico_mount_boss_pilot_d = 1.55;         // M2 自攻底孔；FDM 孔偏小可改 1.60~1.70
pico_support_pad_d = pico_mount_boss_od;  // 兼容旧变量名，实际作为螺柱外径使用

// 左右两组螺柱必须避开 PCB 宽度。
// PCB 宽 20.50mm，若中心距只做 24mm，螺柱外径 5.20mm 时实体仍会靠近 PCB 边；
// 这里改成 26.00mm 中心距，让 M2 底孔和螺柱实体都基本避开 PCB 投影。
pico_mount_boss_pair_dx = 26.00;
pico_support_pad_x = pico_mount_boss_pair_dx / 2;
pico_support_pad_y_top = pico_pcb_h/2 - 13.50;
pico_support_pad_y_bottom = -(pico_pcb_h/2 - 16.00);

// 本版修改：后盖两对 PCB 固定螺柱整体朝“PCB 底部横向挡板”方向平移 5mm。
// 当前 pico_usb_side_y = -1，Type-C 在 -Y 侧，横向挡板在非 Type-C 的 +Y 侧；
// 因此这里用 -pico_usb_side_y 自动得到朝横向挡板方向的平移符号。
pico_mount_boss_shift_to_stop = 5.00;
pico_mount_boss_shift_y = -pico_usb_side_y * pico_mount_boss_shift_to_stop;

pico_mount_boss_inner_clear = pico_mount_boss_pair_dx/2 - pico_mount_boss_od/2 - pico_pcb_w/2;
echo(str("校验：后盖PCB固定=4个M2螺柱，左右两组中心距=", pico_mount_boss_pair_dx, "mm，螺柱内侧距PCB边=", pico_mount_boss_inner_clear, "mm，整体朝横向挡板平移=", pico_mount_boss_shift_to_stop, "mm，外径=", pico_mount_boss_od, "mm，底孔=", pico_mount_boss_pilot_d, "mm；四周弧形小凸点卡扣=", enable_arc_detents ? "启用" : "关闭"));

// PCB 边缘定位/装配间隙。
pico_mount_edge_clear = 0.25;            // PCB 到定位结构的单边装配间隙
pico_capture_h = pico_back_support_h + pico_pcb_t + 0.80; // 边缘挡块总高，略高于 PCB 顶面
pico_mount_wall_t = 1.35;

// 非 Type-C 端横向挡板：替代原来两条间距很近的竖向挡板。
// 距离定义：从后盖 Type-C 口所在短边外缘，沿 PCB 长度方向往内量 54.00mm，
// 到横向挡板靠 Type-C 一侧的面。
pico_rear_stop_bar_from_typec_side = 54.00;
pico_rear_stop_bar_len = pico_pcb_w + 4.20;   // 挡板沿 X 方向，略宽于 PCB，和短边平行
pico_rear_stop_bar_t = 1.35;                 // 挡板厚度，沿 Y 方向
pico_rear_stop_bar_h = pico_capture_h;        // 挡板高度
pico_rear_stop_bar_typec_face_y = pico_usb_side_y * cover_h/2 - pico_usb_side_y * pico_rear_stop_bar_from_typec_side;
pico_rear_stop_bar_y = pico_rear_stop_bar_typec_face_y - pico_usb_side_y * pico_rear_stop_bar_t/2;
echo(str("校验：非Type-C端横向挡板距Type-C侧短边=", pico_rear_stop_bar_from_typec_side, "mm；挡板靠Type-C面Y=", pico_rear_stop_bar_typec_face_y, "mm；挡板中心Y=", pico_rear_stop_bar_y, "mm"));

// 使用原有 4 个 PCB 固定螺柱做小盖板，不再新增任何螺柱。
// 4 个螺柱按上下两组使用：上面左右两个螺柱锁一块小盖板，下面左右两个螺柱锁另一块小盖板。
enable_pico_pair_clamp_covers = true;
pico_pair_clamp_screw_dx = pico_mount_boss_pair_dx;
pico_pair_clamp_y_top = pico_center_y + pico_support_pad_y_top + pico_mount_boss_shift_y;
pico_pair_clamp_y_bottom = pico_center_y + pico_support_pad_y_bottom + pico_mount_boss_shift_y;
pico_pair_clamp_screw_clear_d = 2.40;
pico_pair_clamp_screw_head_d = 4.40;
pico_pair_clamp_screw_head_depth = 0.75;
pico_pair_clamp_cover_t = 1.60;
pico_pair_clamp_cover_w = pico_pair_clamp_screw_dx + pico_mount_boss_od + 4.00;
pico_pair_clamp_cover_h = 7.20;
pico_pair_clamp_cover_r = 1.00;
pico_pair_clamp_press_rib_w = pico_pcb_w - 2.00;
pico_pair_clamp_press_rib_h = 0.45;
pico_pair_clamp_press_rib_len = 3.00;
echo(str("校验：PCB小压盖=2个，使用原4个螺柱；每组左右螺柱中心距=", pico_pair_clamp_screw_dx, "mm；上盖板Y=", pico_pair_clamp_y_top, "mm；下盖板Y=", pico_pair_clamp_y_bottom, "mm；单个盖板尺寸=", pico_pair_clamp_cover_w, " x ", pico_pair_clamp_cover_h, " x ", pico_pair_clamp_cover_t, "mm"));

// 后盖结构坐标校验：四个螺柱、两个 Type-C 侧限位和一个尾部横挡板均应落在后盖范围内。
echo(str("校验：后盖尺寸=", cover_w, " x ", cover_h, "mm；Pico中心X=", pico_center_x, "mm"));
echo(str("校验：四螺柱X=±", pico_support_pad_x, "mm；上排Y=", pico_pair_clamp_y_top, "mm；下排Y=", pico_pair_clamp_y_bottom, "mm"));
echo(str("校验：Type-C侧两个限位中心X=±", pico_lower_clip_side_x, "mm；尾部横挡板中心Y=", pico_rear_stop_bar_y, "mm"));

// Type-C 端左右侧向定位块：只卡 PCB 左右边，不在 Type-C 口前面做横向挡板。
pico_lower_clip_leg_y = 7.00;            // 侧向定位块长度（沿 Y）
pico_lower_clip_side_x = pico_pcb_w/2 + pico_mount_edge_clear + pico_mount_wall_t/2;


// ---------- 右侧长边三按键：6x6x7.3 开关 + φ8 配套键帽 ----------
// 三枚开关安装在前壳 +X 右侧长边，按键轴线沿 X 方向。
// 开关本体在壳内，键帽在壳外，三个按键沿 Y 方向排列。
enable_side_buttons = true;

side_button_center_y = 0.00;
side_button_pitch_y = 10.50;
side_button_center_z = 11.35; // 略向后盖方向移动，为自支撑斜撑和屏幕 PCB 留余量

// 轻触开关本体和方头。
button_switch_body_y = 6.00;
button_switch_body_z = 6.00;
button_switch_body_depth = 3.10; // 沿 X 方向伸入壳内
button_switch_fit_clearance = 0.25;
button_switch_limit_t = 0.90;
button_switch_limit_depth = 1.80;

button_actuator_total_h = 4.20;
button_cap_nominal_w = 2.40;
button_cap_nominal_h = 2.40;
button_cap_x = 1.80;
button_stem_w = 1.60;
button_stem_x = 1.40;
button_collar_x =
    button_actuator_total_h - button_cap_x - button_stem_x;

// 配套键帽图纸。
button_keycap_outer_d = 8.00;
button_keycap_guide_d = 5.60;
button_keycap_total_h = 4.00;
button_keycap_head_h = 3.00;
button_keycap_guide_h =
    button_keycap_total_h - button_keycap_head_h;

// 右侧壁键帽孔。
// φ6.10 对 φ5.60 导向套提供单边 0.25mm 理论间隙。
button_keycap_hole_d = 6.10;
button_keycap_entry_d = 6.50;
button_keycap_entry_depth = 0.35;

// 侧壁加强：不在按键孔背后整面加厚，避免减少方头外露长度。
// 仅在按键组上下增加连续加强筋，并用每个开关的限位框补强孔周。
side_button_reinforce_depth = 1.30;
side_button_reinforce_len_y = 34.00;
side_button_reinforce_bar_z = 1.20;

// 侧向压紧结构。
// 开关本体沿 X 深 3.10mm；螺柱比本体短 0.08mm，锁紧后轻压。
side_button_clamp_preload = 0.08;
side_button_post_len =
    button_switch_body_depth - side_button_clamp_preload;
side_button_post_y = 18.00;
side_button_post_od = 4.80;       // 保留兼容参数，代表原圆柱外径
side_button_post_pilot_d = 1.55;

// FDM 自支撑螺柱参数。
// 原横向圆柱底面会悬空，改成有平整承压面的方形螺柱座，并在下方增加 45°斜撑。
side_button_post_body_y = 5.60;   // 沿 Y 的承压面宽度，比原 φ4.8 略宽
side_button_post_body_z = 4.80;   // 沿 Z 的承压面高度
side_button_gusset_y = 6.20;      // 45°斜撑沿 Y 的宽度
side_button_gusset_skin = 0.28;   // hull 端部薄片厚度，避免共面布尔问题

// 横向 M2 底孔改为水滴形：下部接近圆孔，顶部形成尖角，打印时不需要跨越圆弧顶部。
side_button_pilot_teardrop_top = 1.55; // 顶部尖角相对圆心的高度倍数
side_button_pilot_mouth_relief = 0.15; // 螺柱内端入口轻微放宽

// 独立侧按键压板：本地坐标中宽度沿按键排列方向，高度沿外壳 Z。
side_button_plate_w = 44.00;
side_button_plate_h = 9.00;
side_button_plate_t = 1.80;
side_button_plate_r = 1.20;
side_button_plate_screw_clear_d = 2.40;
side_button_plate_head_d = 4.40;
side_button_plate_head_depth = 0.75;

// 开关四脚孔：侧装后 6.50mm 映射到 Y，4.50mm 映射到 Z。
button_pin_dy = 6.50;
button_pin_dz = 4.50;
button_pin_hole_d = 1.35;
button_center_relief_d = 2.80;

// 关键坐标。
side_button_outer_x = body_w/2;
side_button_inner_x = body_w/2 - wall;
side_button_plate_outer_x =
    side_button_inner_x - side_button_post_len;

side_button_locator_half_y =
    (button_switch_body_y + 2*button_switch_fit_clearance)/2
    + button_switch_limit_t;
side_button_locator_half_z =
    (button_switch_body_z + 2*button_switch_fit_clearance)/2
    + button_switch_limit_t;

side_button_keycap_edge_gap =
    side_button_pitch_y - button_keycap_outer_d;
side_button_z_min =
    side_button_center_z - side_button_locator_half_z;
side_button_z_max =
    side_button_center_z + side_button_locator_half_z;

echo(str("校验：右侧按键中心Y=",
         side_button_center_y - side_button_pitch_y, ", ",
         side_button_center_y, ", ",
         side_button_center_y + side_button_pitch_y,
         "mm；中心Z=", side_button_center_z, "mm"));
echo(str("校验：键帽φ", button_keycap_outer_d,
         "；导向套φ", button_keycap_guide_d,
         "；侧壁孔φ", button_keycap_hole_d,
         "；相邻键帽边缘间隙=", side_button_keycap_edge_gap, "mm"));
echo(str("校验：侧按键结构Z范围=", side_button_z_min, "~",
         side_button_z_max, "mm；屏幕PCB后表面约Z=",
         front_thick + screen_support_h + screen_pcb_t,
         "mm；后盖台阶起点Z=", shell_depth - cover_t, "mm"));
echo(str("校验：侧压板=", side_button_plate_w, " x ",
         side_button_plate_h, " x ", side_button_plate_t,
         "mm；M2螺柱Y=±", side_button_post_y,
         "mm；螺柱长度=", side_button_post_len, "mm"));
echo(str("校验：侧螺柱已启用FDM自支撑结构；方形承压面=",
         side_button_post_body_y, " x ", side_button_post_body_z,
         "mm；45度斜撑宽=", side_button_gusset_y,
         "mm；水滴底孔基准直径=", side_button_post_pilot_d, "mm"));

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
  // 屏幕安装孔以 PCB 中心为原点；当前中心距为 37.70 x 65.80mm。
  for (x = [-screen_hole_dx/2, screen_hole_dx/2])
    for (y = [-screen_hole_dy/2, screen_hole_dy/2])
      translate([x, y, 0]) children();
}



module pico_board_support_rails() {
  // 两条窄支撑轨只托住 Pico PCB 背面，定位仍完全依赖 Type-C 限位座。
  if (enable_pico_board_support_rails) {
    for (sx = [-1, 1])
      add_box(pico_rail_w, pico_rail_h, pico_standoff_h,
              pico_center_x + sx * pico_rail_x_offset,
              pico_rail_y,
              cover_t);
  }
}

module typec_locator_side_tab(sx, y, y_len, side_clearance) {
  // 短点接触侧向定位：比整条夹槽更适合 3D 打印，误差不会沿整条边累积。
  side_x = typec_shell_w/2 + side_clearance + typec_locator_wall_t/2;
  add_box(typec_locator_wall_t, y_len, typec_locator_h,
          pico_center_x + sx * side_x,
          y,
          typec_shell_local_z0);
}

module typec_locator_lead_in_guide(sx) {
  // 入口导向做成外宽内窄的斜导向块。
  // 作用是把 Type-C 自然导入最终定位点，不靠蛮力硬塞。
  guide_front_y = typec_shell_center_y + pico_usb_side_y * (typec_shell_d/2 + 0.25);
  guide_rear_y  = typec_shell_center_y + pico_usb_side_y * (typec_shell_d/2 - typec_lead_in_len);
  guide_front_x = typec_shell_w/2 + typec_guide_side_clearance + typec_locator_wall_t/2;
  guide_rear_x  = typec_shell_w/2 + typec_final_side_clearance + 0.18 + typec_locator_wall_t/2;

  hull() {
    add_box(typec_locator_wall_t, 0.55, typec_locator_h,
            pico_center_x + sx * guide_front_x,
            guide_front_y,
            typec_shell_local_z0);
    add_box(typec_locator_wall_t, 0.55, typec_locator_h,
            pico_center_x + sx * guide_rear_x,
            guide_rear_y,
            typec_shell_local_z0);
  }
}

module typec_locator_seat() {
  if (enable_typec_locator_lock) {
    // 1) 入口导向：靠近外壳 Type-C 开孔的位置做宽松喇叭口，避免打印毛刺影响插入。
    for (sx = [-1, 1])
      typec_locator_lead_in_guide(sx);

    // 2) 最终侧向定位：每边只做前后两个短凸台，减少摩擦面积。
    front_tab_y = typec_shell_center_y + pico_usb_side_y * (typec_shell_d/2 - typec_locator_front_relief - typec_locator_point_len/2);
    rear_tab_y  = typec_shell_center_y - pico_usb_side_y * (typec_shell_d/2 - typec_locator_point_len/2);
    for (sx = [-1, 1]) {
      typec_locator_side_tab(sx, front_tab_y, typec_locator_point_len, typec_final_side_clearance);
      typec_locator_side_tab(sx, rear_tab_y,  typec_locator_point_len, typec_final_side_clearance);
    }

    // 3) 后挡块：挡在 Type-C 座体后端，防止 PCB/USB 座装上后从后面直接滑走。
    //    这里离 Type-C 后端仍有 XY 余量，不会把连接器硬顶死。
    rear_y = typec_shell_center_y - pico_usb_side_y * (typec_shell_d/2 + typec_fdm_xy_clearance + typec_stop_wall_t/2);
    add_box(typec_shell_w + 2*typec_final_side_clearance + 2*typec_locator_wall_t,
            typec_stop_wall_t,
            typec_locator_h,
            pico_center_x,
            rear_y,
            typec_shell_local_z0);

    // 4) 底部托点：左右各一小块，避免大面积托底碰到不同 Pico 板上的元件或焊脚。
    //    托点只负责抗翘，不负责决定 Type-C 口面位置。
    for (sx = [-1, 1])
      add_box(typec_bottom_pad_w, typec_bottom_pad_len, typec_bottom_pad_h,
              pico_center_x + sx * (typec_shell_w/2 - typec_bottom_pad_w/2 - 0.60),
              typec_shell_center_y - pico_usb_side_y * 0.40,
              typec_shell_local_z0 - typec_bottom_pad_h);
  }
}

module typec_clamp_bosses() {
  if (enable_typec_locator_lock) {
    for (x = [-typec_clamp_screw_dx/2, typec_clamp_screw_dx/2]) {
      // 螺丝柱底部加宽一点，减少高柱在插拔受力时折断的概率。
      add_box(typec_clamp_boss_od + 1.40, typec_clamp_boss_od + 1.40, 0.80,
              pico_center_x + x, typec_clamp_screw_y, cover_t);
      translate([pico_center_x + x, typec_clamp_screw_y, cover_t])
        cylinder(d = typec_clamp_boss_od, h = typec_clamp_boss_h);
    }
  }
}

module typec_clamp_boss_holes() {
  if (enable_typec_locator_lock) {
    for (x = [-typec_clamp_screw_dx/2, typec_clamp_screw_dx/2])
      translate([pico_center_x + x, typec_clamp_screw_y, cover_t + 0.60])
        cylinder(d = typec_clamp_boss_pilot_d, h = max(0.10, typec_clamp_boss_h - 0.20));
  }
}

module typec_clamp_cover() {
  // 独立打印的小压盖：两个 M2 通孔，对应后盖上的两个高螺丝柱。
  // 压盖底面接近 Type-C 座体外侧，配合两颗 M2 螺丝形成轻压紧。
  // 默认 typec_clamp_limit_gap = 0.05mm，FDM 实际通常接近贴合；想更紧可改 0 或 -0.05。
  // 它负责防止连接器上抬、后退，以及分担插拔时的晃动。
  difference() {
    union() {
      rounded_prism(typec_clamp_cover_w, typec_clamp_cover_h, typec_clamp_cover_t, typec_clamp_cover_r);

      // 外侧加强筋：增加压盖抗弯，避免螺丝一锁中间翘起来。
      add_box(typec_clamp_stiffener_w, 1.40, typec_clamp_stiffener_h,
              0,
              typec_clamp_stiffener_y,
              typec_clamp_cover_t);
    }

    // M2 通孔。FDM 孔会偏小，所以默认给到 2.40mm。
    for (x = [-typec_clamp_screw_dx/2, typec_clamp_screw_dx/2])
      translate([x, 0, -0.30])
        cylinder(d = typec_clamp_screw_clear_d, h = typec_clamp_cover_t + typec_clamp_stiffener_h + 1.20);

    // 螺丝头避让/浅沉孔，避免螺丝头凸得太高。
    for (x = [-typec_clamp_screw_dx/2, typec_clamp_screw_dx/2])
      translate([x, 0, typec_clamp_cover_t - typec_clamp_screw_head_depth])
        cylinder(d = typec_clamp_screw_head_d, h = typec_clamp_screw_head_depth + typec_clamp_stiffener_h + 0.60);

    // 插口前沿小避让：避免压到 Type-C 口沿/焊壳毛刺；主体底面仍然负责压住座体。
    translate([0, pico_usb_side_y * (typec_shell_d/2 - 0.70), -0.05])
      rounded_cut(typec_shell_w - 1.20, 1.20, 0.18, 0.35, 0, 0, 0);
  }
}

module typec_clamp_cover_installed_local() {
  translate([pico_center_x, typec_clamp_screw_y, typec_clamp_cover_local_z0])
    typec_clamp_cover();
}

module assembled_typec_clamp_cover() {
  // 装配预览：压盖和后盖一样绕 Y 轴翻转到外壳内部。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      typec_clamp_cover_installed_local();
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


module at_pico_support_pads() {
  // 4 个圆形支撑点，位置参考你 SVG 草图里的 4 个圆。
  // 本版 4 个螺柱整体朝 PCB 底部横向挡板方向平移 pico_mount_boss_shift_to_stop。
  for (x = [-pico_support_pad_x, pico_support_pad_x]) {

    translate([
      pico_center_x + x + pico_mount_boss_shift_x,
      pico_center_y + pico_support_pad_y_top + pico_mount_boss_shift_y,
      0
    ])
      children();

    translate([
      pico_center_x + x + pico_mount_boss_shift_x,
      pico_center_y + pico_support_pad_y_bottom + pico_mount_boss_shift_y,
      0
    ])
      children();
  }
}

module pico_svg_top_capture_tabs() {
  // 非 Type-C 端横向挡板：与短边平行，替代原来两条间距很近的竖向挡板。
  // 注意：这里的 54mm 是从后盖 Type-C 口所在短边外缘，量到挡板靠 Type-C 的那一面。
  if (enable_pico_svg_mount) {
    add_box(pico_rear_stop_bar_len,
            pico_rear_stop_bar_t,
            pico_rear_stop_bar_h,
            pico_center_x + pico_mount_boss_shift_x,
            pico_rear_stop_bar_y,
            cover_t);
  }
}
module pico_pair_clamp_cover() {
  // 使用原来的左右两个 PCB 螺柱固定一块小盖板。
  // 这个模块会打印两份：分别对应原有 4 个螺柱中的上面一组和下面一组。
  difference() {
    union() {
      rounded_prism(pico_pair_clamp_cover_w,
                    pico_pair_clamp_cover_h,
                    pico_pair_clamp_cover_t,
                    pico_pair_clamp_cover_r);

      // 中央浅压筋：只在两个螺丝之间轻压 PCB 平整背面。
      add_box(pico_pair_clamp_press_rib_w,
              pico_pair_clamp_press_rib_len,
              pico_pair_clamp_press_rib_h,
              0, 0, pico_pair_clamp_cover_t);
    }

    // 两个 M2 通孔，对应同一排左右两个原有 PCB 螺柱。
    for (x = [-pico_pair_clamp_screw_dx/2, pico_pair_clamp_screw_dx/2])
      translate([x, 0, -0.30])
        cylinder(d = pico_pair_clamp_screw_clear_d,
                 h = pico_pair_clamp_cover_t + pico_pair_clamp_press_rib_h + 1.20);

    // 螺丝头浅沉孔/避让。
    for (x = [-pico_pair_clamp_screw_dx/2, pico_pair_clamp_screw_dx/2])
      translate([x, 0, pico_pair_clamp_cover_t - pico_pair_clamp_screw_head_depth])
        cylinder(d = pico_pair_clamp_screw_head_d,
                 h = pico_pair_clamp_screw_head_depth + pico_pair_clamp_press_rib_h + 0.60);
  }
}

module pico_pair_clamp_covers_installed_local() {
  // 装配预览用：两块小盖板分别放在原 4 个 PCB 螺柱的上下两组上方。
  if (enable_pico_svg_mount && enable_pico_pair_clamp_covers) {
    translate([pico_center_x + pico_mount_boss_shift_x,
               pico_pair_clamp_y_top,
               cover_t + pico_back_support_h])
      pico_pair_clamp_cover();

    translate([pico_center_x + pico_mount_boss_shift_x,
               pico_pair_clamp_y_bottom,
               cover_t + pico_back_support_h])
      pico_pair_clamp_cover();
  }
}

module assembled_pico_pair_clamp_covers() {
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      pico_pair_clamp_covers_installed_local();
}

module pico_svg_lower_l_clips() {
  // Type-C 端只保留左右侧向定位块。
  // 这里故意删掉原来的前方横向挡板，避免挡住 Type-C 口和座体前端元件。
  if (enable_pico_svg_mount) {
    bottom_edge_y = pico_center_y - pico_pcb_h/2;

    for (sx = [-1, 1]) {
        clip_x = pico_center_x + sx * pico_lower_clip_side_x + pico_mount_boss_shift_x;

      // 侧向定位块：沿 PCB 左右侧边向上限位，只卡板边，不压电子元件面。
      add_box(pico_mount_wall_t,
              pico_lower_clip_leg_y,
              pico_capture_h,
              clip_x,
              bottom_edge_y + pico_lower_clip_leg_y/2,
              cover_t);
    }
  }
}

module pico_svg_mount_features() {
  if (enable_pico_svg_mount) {
    // 4 个圆形 M2 螺柱：位于 PCB 左右两侧，上下各一组，供两块小压盖锁紧。
    at_pico_support_pads()
      translate([0, 0, cover_t])
        cylinder(d = pico_mount_boss_od, h = pico_back_support_h);

    // 顶边小挡边：只辅助定位非 Type-C 端，不作为主要压紧结构。
    pico_svg_top_capture_tabs();

    // 小盖板使用上面 4 个 PCB 螺柱，不在后盖上新增螺柱。

    // Type-C 端左右侧向定位块：不再做口前横向挡板。
    pico_svg_lower_l_clips();
  }
}

module pico_svg_mount_boss_holes() {
  if (enable_pico_svg_mount) {
    // M2 自攻底孔：从螺柱顶部向下打孔，底部保留约 0.4mm 不穿透后盖外表面。
    at_pico_support_pads()
      translate([0, 0, cover_t + 0.40])
        cylinder(d = pico_mount_boss_pilot_d, h = pico_back_support_h + 0.40);
  }
}


// ---------- 右侧三按键定位、开孔、螺柱和压板 ----------
module at_side_button_positions() {
  if (enable_side_buttons)
    for (y_offset = [-side_button_pitch_y, 0, side_button_pitch_y])
      translate([0, side_button_center_y + y_offset,
                 side_button_center_z])
        children();
}

module at_side_button_plate_positions() {
  if (enable_side_buttons)
    for (u = [-side_button_pitch_y, 0, side_button_pitch_y])
      translate([u, 0, 0])
        children();
}

module at_side_button_post_positions() {
  if (enable_side_buttons)
    for (sy = [-1, 1])
      translate([0, side_button_center_y + sy*side_button_post_y,
                 side_button_center_z])
        children();
}

module at_side_button_plate_screw_positions() {
  if (enable_side_buttons)
    for (su = [-1, 1])
      translate([su*side_button_post_y, 0, 0])
        children();
}

module side_button_reinforcement() {
  if (enable_side_buttons) {
    x0 = side_button_inner_x - side_button_reinforce_depth;
    rail_offset_z =
        button_switch_body_z/2
        + button_switch_fit_clearance
        + button_switch_limit_t/2;

    // 上下两条连续加强筋，避开按键中心孔，保持侧壁孔处仍为原 1.8mm 厚。
    for (sz = [-1, 1])
      translate([
        x0,
        side_button_center_y - side_button_reinforce_len_y/2,
        side_button_center_z
          + sz*rail_offset_z
          - side_button_reinforce_bar_z/2
      ])
        cube([
          side_button_reinforce_depth,
          side_button_reinforce_len_y,
          side_button_reinforce_bar_z
        ]);
  }
}

module side_button_locator_one() {
  // 开关 6x6 面贴在右侧壁内表面，四条短筋只限制 Y/Z 位移。
  inner_y =
      button_switch_body_y + 2*button_switch_fit_clearance;
  inner_z =
      button_switch_body_z + 2*button_switch_fit_clearance;
  t = button_switch_limit_t;
  depth = button_switch_limit_depth;
  x0 = side_button_inner_x - depth;

  // Y 两侧限位筋。
  translate([x0, -inner_y/2 - t, -inner_z/2 - t])
    cube([depth, t, inner_z + 2*t]);
  translate([x0,  inner_y/2,     -inner_z/2 - t])
    cube([depth, t, inner_z + 2*t]);

  // Z 上下限位筋。
  translate([x0, -inner_y/2, -inner_z/2 - t])
    cube([depth, inner_y, t]);
  translate([x0, -inner_y/2,  inner_z/2])
    cube([depth, inner_y, t]);
}

module side_button_switch_locators() {
  at_side_button_positions()
    side_button_locator_one();
}

module side_button_post_one_supportless() {
  // 本模块以螺丝轴心为局部原点。
  //
  // 主承压座改成矩形截面：
  //   - 内端为完整平面，侧按键压板锁紧时受力更均匀；
  //   - 不再依赖横向圆柱最底部的悬空圆弧。
  x_inner = side_button_inner_x - side_button_post_len;
  half_y = side_button_post_body_y/2;
  half_z = side_button_post_body_z/2;

  translate([x_inner, -half_y, -half_z])
    cube([
      side_button_post_len,
      side_button_post_body_y,
      side_button_post_body_z
    ]);

  // 下方 45°自支撑斜撑：
  //   - 靠侧壁的一端降低 side_button_post_len；
  //   - 靠压板的一端正好托住主承压座底面；
  //   - 正面朝下打印时，每层只向壳内扩展约一个层高，不需要切片支撑。
  hull() {
    translate([
      side_button_inner_x - side_button_gusset_skin,
      -side_button_gusset_y/2,
      -half_z - side_button_post_len
    ])
      cube([
        side_button_gusset_skin,
        side_button_gusset_y,
        side_button_gusset_skin
      ]);

    translate([
      x_inner,
      -side_button_gusset_y/2,
      -half_z
    ])
      cube([
        side_button_gusset_skin,
        side_button_gusset_y,
        side_button_gusset_skin
      ]);
  }

  // 根部上下增加短圆角替代筋，降低反复按压导致的应力集中。
  for (sz = [-1, 1])
    hull() {
      translate([
        side_button_inner_x - 0.45,
        -side_button_post_body_y/2,
        sz*(half_z - 0.35) - 0.35
      ])
        cube([0.45, side_button_post_body_y, 0.70]);

      translate([
        side_button_inner_x - 1.10,
        -side_button_post_body_y/2,
        sz*(half_z - 0.15) - 0.20
      ])
        cube([0.35, side_button_post_body_y, 0.40]);
    }
}

module side_button_posts() {
  if (enable_side_buttons)
    at_side_button_post_positions()
      side_button_post_one_supportless();
}

module side_button_teardrop_pilot_x(d, length) {
  // 水滴孔截面位于 Y-Z 平面，沿 +X 拉伸。
  // 圆孔顶部额外增加一个尖角，切片时顶部由两条斜线逐层闭合，不会形成长桥接。
  r = d/2;

  rotate([0, 90, 0])
    linear_extrude(height = length)
      union() {
        circle(d = d);

        // 旋转后二维 -X 方向对应三维 +Z，因此尖角写在二维负 X 一侧。
        polygon(points = [
          [-r*side_button_pilot_teardrop_top, 0],
          [-r*0.15, -r*0.78],
          [-r*0.15,  r*0.78]
        ]);
      }
}

module side_button_post_hole_cuts() {
  // 从螺柱内端向侧壁开 M2 自攻水滴底孔。
  // 侧壁一端保留约 0.45mm 实体，不会穿透外壳。
  pilot_len = max(0.80, side_button_post_len - 0.45);

  if (enable_side_buttons)
    at_side_button_post_positions() {
      translate([
        side_button_inner_x - side_button_post_len - 0.05,
        0, 0
      ])
        side_button_teardrop_pilot_x(
          side_button_post_pilot_d,
          pilot_len
        );

      // 内端增加很浅的圆形导入口，方便 M2 螺丝找正；
      // 深度很短，不会重新引入明显的横孔塌顶问题。
      translate([
        side_button_inner_x
          - side_button_post_len
          - side_button_pilot_mouth_relief,
        0, 0
      ])
        rotate([0, 90, 0])
          cylinder(
            d = side_button_post_pilot_d + 0.25,
            h = side_button_pilot_mouth_relief + 0.08
          );
    }
}

module side_button_hole_cuts() {
  if (enable_side_buttons)
    at_side_button_positions() {
      // φ6.10 主孔贯穿右侧壁。
      translate([side_button_inner_x - 0.35, 0, 0])
        rotate([0, 90, 0])
          cylinder(d = button_keycap_hole_d,
                   h = wall + 0.70);

      // 外侧 φ6.50 x 0.35mm 浅导入口，去除横向圆孔顶部毛边。
      translate([
        side_button_outer_x - button_keycap_entry_depth,
        0, 0
      ])
        rotate([0, 90, 0])
          cylinder(d = button_keycap_entry_d,
                   h = button_keycap_entry_depth + 0.12);
    }
}

module side_button_plate_raw() {
  // 独立压板以平面姿态建模，方便直接打印。
  // 本地 X 对应装配后的 Y，本地 Y 对应装配后的 Z。
  difference() {
    rounded_prism(side_button_plate_w,
                  side_button_plate_h,
                  side_button_plate_t,
                  side_button_plate_r);

    // 两个 M2 通孔。
    at_side_button_plate_screw_positions()
      translate([0, 0, -0.30])
        cylinder(d = side_button_plate_screw_clear_d,
                 h = side_button_plate_t + 0.60);

    // 螺丝头浅沉孔。
    at_side_button_plate_screw_positions()
      translate([
        0, 0,
        side_button_plate_t - side_button_plate_head_depth
      ])
        cylinder(d = side_button_plate_head_d,
                 h = side_button_plate_head_depth + 0.30);

    // 每个侧装开关的四个引脚孔和中央避让孔。
    at_side_button_plate_positions() {
      for (py = [-button_pin_dy/2, button_pin_dy/2])
        for (pz = [-button_pin_dz/2, button_pin_dz/2])
          translate([py, pz, -0.30])
            cylinder(d = button_pin_hole_d,
                     h = side_button_plate_t + 0.60);

      translate([0, 0, -0.30])
        cylinder(d = button_center_relief_d,
                 h = side_button_plate_t + 0.60);
    }
  }
}

module side_button_plate_installed() {
  // 坐标映射：
  //   压板本地 X -> 外壳 Y
  //   压板本地 Y -> 外壳 Z
  //   压板本地 Z -> 外壳 -X
  multmatrix([
    [0, 0, -1, side_button_plate_outer_x],
    [1, 0,  0, side_button_center_y],
    [0, 1,  0, side_button_center_z],
    [0, 0,  0, 1]
  ])
    side_button_plate_raw();
}

module side_button_switch_references() {
  if (enable_side_buttons)
    at_side_button_positions() {
      // 开关塑料本体：靠右侧壁，沿 X 向壳内延伸 3.1mm。
      color([0.12, 0.12, 0.12, 0.55])
        translate([
          side_button_inner_x - button_switch_body_depth/2,
          0, 0
        ])
          cube([
            button_switch_body_depth,
            button_switch_body_y,
            button_switch_body_z
          ], center = true);

      // 开关圆形基座、方柄和 2.4mm 方头，朝 +X 外侧。
      color([0.14, 0.14, 0.14, 0.65])
        translate([side_button_inner_x, 0, 0])
          rotate([0, 90, 0])
            cylinder(d = 3.20, h = button_collar_x);

      color([0.08, 0.08, 0.08, 0.70])
        translate([
          side_button_inner_x + button_collar_x,
          -button_stem_w/2,
          -button_stem_w/2
        ])
          cube([button_stem_x, button_stem_w, button_stem_w]);

      color([0.02, 0.02, 0.02, 0.80])
        translate([
          side_button_inner_x + button_collar_x + button_stem_x,
          -button_cap_nominal_w/2,
          -button_cap_nominal_h/2
        ])
          cube([
            button_cap_x,
            button_cap_nominal_w,
            button_cap_nominal_h
          ]);

      // φ8 配套键帽：φ5.6 导向套进入侧壁，φ8 主帽位于外侧。
      color([0.08, 0.08, 0.08, 0.72])
        translate([
          side_button_outer_x - button_keycap_guide_h,
          0, 0
        ])
          rotate([0, 90, 0])
            cylinder(d = button_keycap_guide_d,
                     h = button_keycap_guide_h);

      color([0.05, 0.05, 0.05, 0.82])
        translate([side_button_outer_x, 0, 0])
          rotate([0, 90, 0])
            cylinder(d = button_keycap_outer_d,
                     h = button_keycap_head_h);
    }
}

// ---------- 前壳 ----------
module screen_mount_bosses() {
  // 四个安装螺柱向前面板内嵌，顶部安装高度保持不变。
  //
  // 旧版 φ5.60 同心底座会朝屏幕中心扩张，进入
  // 43.90 x 61.50mm 的显示外框凹槽。
  // 本版主柱缩为 φ4.00，并把加固材料只放在 PCB 外缘方向。
  for (x = [-screen_hole_dx/2, screen_hole_dx/2])
    for (sy = [-1, 1]) {
      y = sy * screen_hole_dy/2;
      z0 = front_thick - screen_boss_embed;

      // 主螺柱：与显示外框凹槽保持间隙。
      translate([x, y, z0])
        cylinder(
          d = screen_boss_od,
          h = screen_support_h + screen_boss_embed
        );

      // 偏心加固脚：
      // 上排只向 +Y 外缘延伸，下排只向 -Y 外缘延伸。
      // hull 与主柱根部连接，不向显示区方向增加半径。
      hull() {
        translate([x, y, z0])
          cylinder(
            d = screen_boss_od,
            h = screen_boss_embed + screen_boss_anchor_h
          );

        translate([
          x,
          y + sy*screen_boss_anchor_shift_y,
          z0
        ])
          cylinder(
            d = screen_boss_anchor_od,
            h = screen_boss_anchor_embed
                + screen_boss_anchor_h
          );
      }
    }
}

module screen_locator_lips() {
  // 定位槽内尺寸 = PCB 标称尺寸 + fit_clearance。
  x_lip =
      screen_locator_w/2 + screen_lip_t/2;
  y_lip =
      screen_locator_h/2 + screen_lip_t/2;

  lip_z0 = front_thick - screen_lip_embed;
  lip_h_real = screen_lip_h + screen_lip_embed;

  // 左右定位边。
  add_box(
    screen_lip_t,
    screen_locator_h + 2*screen_lip_t,
    lip_h_real,
    -x_lip, 0, lip_z0
  );
  add_box(
    screen_lip_t,
    screen_locator_h + 2*screen_lip_t,
    lip_h_real,
    x_lip, 0, lip_z0
  );

  // 下边完整定位。
  add_box(
    screen_locator_w + 2*screen_lip_t,
    screen_lip_t,
    lip_h_real,
    0, -y_lip, lip_z0
  );

  // 上边避开排针，拆成两段。
  upper_segment_w = screen_pcb_w/2 - 3.00;
  upper_segment_x = screen_pcb_w/4 + 1.50;

  add_box(
    upper_segment_w,
    screen_lip_t,
    lip_h_real,
    -upper_segment_x, y_lip, lip_z0
  );
  add_box(
    upper_segment_w,
    screen_lip_t,
    lip_h_real,
    upper_segment_x, y_lip, lip_z0
  );
}

module rear_rabbet_cut() {
  // 后口削薄形成台阶，后盖落入这里再点胶。
  translate([0, 0, shell_depth - rear_rebate_depth])
    rounded_prism(rear_rebate_w, rear_rebate_h,
                  rear_rebate_depth + 0.80,
                  max(0.10, corner_r - rear_edge_wall));
}

module front_screen_inner_relief() {
  // 按 43.50 x 61.10mm 显示外框开浅避让槽。
  // 这里只削薄前面板内侧，不改变正面开窗。
  rounded_cut(
    screen_bl_relief_w,
    screen_bl_relief_h,
    screen_bl_relief_depth + 0.05,
    screen_bl_relief_r,
    0,
    screen_bl_relief_y_offset,
    front_thick - screen_bl_relief_depth
  );
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

        // 正面可视开窗。
        rounded_cut(screen_window_w, screen_window_h,
                    front_thick + 1.20, screen_window_r,
                    0, screen_window_y_offset, -0.60);

        // 内侧显示组件避让槽。
        front_screen_inner_relief();
      }

      // 四个屏幕 M2 主柱嵌入前面板，并使用向 PCB 外缘偏移的加固脚；
      // 加固材料不会再侵入显示外框凹槽。
      screen_mount_bosses();

      // 屏幕 PCB 定位边。
      screen_locator_lips();

      // 右侧三按键孔周加强和 6x6 开关限位框。
      side_button_reinforcement();
      side_button_switch_locators();

      // 右侧按键独立压板的两个横向 M2 螺柱。
      side_button_posts();
    }

    // Type-C 短边开孔。
    side_typec_cut(typec_open_w, typec_open_h,
                   typec_cut_depth, typec_open_r,
                   typec_open_x, typec_open_y,
                   typec_open_center_z);

    // 右侧长边三个键帽导向孔。
    side_button_hole_cuts();

    // 右侧按键压板螺柱 M2 盲孔。
    side_button_post_hole_cuts();

    // 后盖凸点对应的前壳浅凹窝。
    front_shell_arc_scoop_cuts();

    // 屏幕 M2 自攻底孔。
    // 孔底停在 Z=front_thick，前面板内部的 0.60mm 锚固层不切穿。
    screen_pilot_top_z =
        front_thick + screen_support_h + 0.35;
    screen_pilot_bottom_z = front_thick;

    at_screen_holes()
      translate([0, 0, screen_pilot_bottom_z])
        cylinder(
          d = screen_boss_pilot_d,
          h = screen_pilot_top_z - screen_pilot_bottom_z
        );
  }
}

// ---------- 后盖 ----------
module back_cover() {
  // 后盖只保留 Pico 四螺柱、两块小压盖对应结构、
  // Type-C 侧两个限位、非 Type-C 端横向挡板和四周弧形凸点。
  // 三枚按键已经全部迁移到前壳右侧长边。
  difference() {
    union() {
      rounded_prism(
        cover_w,
        cover_h,
        cover_t,
        max(0.10,
            corner_r - rear_edge_wall
            - cover_clearance/2)
      );

      rear_cover_arc_detents();
      pico_svg_mount_features();
    }

    // 四个 Pico 小压盖固定螺柱的 M2 自攻底孔。
    pico_svg_mount_boss_holes();
  }
}

// ---------- 同平面打印布局 ----------
module print_plate() {
  // 左侧：前壳屏幕面朝下。
  translate([-(body_w/2 + plate_gap/2), 0, 0])
    front_shell();

  // 右侧：后盖外侧朝下。
  translate([(cover_w/2 + plate_gap/2), 0, 0])
    back_cover();

  // 两块 Pico PCB 小压盖。
  translate([
    (cover_w/2 + plate_gap/2),
    -(cover_h/2
      + pico_pair_clamp_cover_h/2
      + plate_gap/2),
    0
  ])
    pico_pair_clamp_cover();

  translate([
    (cover_w/2 + plate_gap/2),
    -(cover_h/2
      + pico_pair_clamp_cover_h*1.5
      + plate_gap/2 + 3.00),
    0
  ])
    pico_pair_clamp_cover();

  // 右侧三按键共用压板，以平面姿态打印。
  translate([
    -(body_w/2 + plate_gap/2),
    -(body_h/2
      + side_button_plate_h/2
      + plate_gap/2),
    0
  ])
    side_button_plate_raw();
}

// ---------- 预览参考 ----------
module screen_reference() {
  // PCB 外形参考。
  color([0.0, 0.7, 0.1, 0.24])
    translate([
      0, 0,
      front_thick + screen_support_h + screen_pcb_t/2
    ])
      cube(
        [screen_pcb_w, screen_pcb_h, screen_pcb_t],
        center = true
      );

  // 43.50 x 61.10mm 显示外框参考。
  color([0.30, 0.30, 0.30, 0.20])
    translate([
      0, screen_shell_y_offset,
      front_thick + 0.35
    ])
      cube(
        [screen_shell_w, screen_shell_h, 0.30],
        center = true
      );

  // 42.72 x 58.80mm BL 参考。
  color([0.10, 0.30, 0.60, 0.18])
    translate([
      0, screen_bl_y_offset,
      front_thick + 0.22
    ])
      cube(
        [screen_bl_w, screen_bl_h, 0.24],
        center = true
      );

  // 37.90 x 49.80mm 图纸可视框参考。
  color([0.70, 0.45, 0.05, 0.22])
    translate([
      0, screen_view_y_offset,
      front_thick + 0.12
    ])
      cube(
        [screen_view_w, screen_view_h, 0.20],
        center = true
      );

  // 37.42 x 49.66mm VA 有效显示区。
  color([0.0, 0.0, 0.0, 0.38])
    translate([
      0, screen_aa_y_offset,
      front_thick + 0.02
    ])
      cube(
        [screen_aa_w, screen_aa_h, 0.18],
        center = true
      );

  // 四个 φ2.10 安装孔参考点。
  color([1.0, 0.0, 0.0, 0.70])
    at_screen_holes()
      translate([
        0, 0,
        front_thick + screen_support_h
        + screen_pcb_t + 0.25
      ])
        cylinder(
          d = screen_hole_d,
          h = 0.50,
          center = true
        );
}

module pico_reference() {
  // Pico PCB 外形参考。
  color([0.05, 0.20, 0.90, 0.28])
    translate([pico_center_x, pico_center_y, pico_board_center_z])
      cube([pico_pcb_w, pico_pcb_h, pico_pcb_t], center = true);

  // Type-C 连接器本体参考：由口面位置和连接器尺寸反推，和 Pico 板长无关。
  color([1.0, 0.45, 0.10, 0.55])
    translate([pico_center_x, typec_shell_center_y, typec_open_center_z])
      cube([typec_shell_w, typec_shell_d, typec_shell_h], center = true);

  // Type-C 口面参考线，装配时应正对外壳 Type-C 开孔。
  color([1.0, 0.10, 0.10, 0.70])
    translate([pico_center_x, typec_connector_mouth_y, typec_open_center_z])
      cube([typec_open_w, 0.40, typec_open_h], center = true);
}

module assembled_back_cover() {
  // 后盖装配预览：绕 Y 轴翻转，使后盖内部结构朝向前壳。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      back_cover();
}

// ---------- Type-C 限位测试小样 ----------
module typec_fit_test() {
  // 只打印 Type-C 限位座的一小块，用来先测 FDM 公差。
  // 测试通过后再打印完整后盖，避免因为 0.1~0.2mm 误差浪费大件。
  test_plate_w = typec_shell_w + 2*typec_guide_side_clearance + 2*typec_locator_wall_t + 5.00;
  test_plate_h = typec_shell_d + typec_lead_in_len + typec_stop_wall_t + 6.00;
  test_plate_t = 1.60;

  union() {
    rounded_prism(test_plate_w, test_plate_h, test_plate_t, 1.20);

    // 把原本位于后盖坐标里的限位座平移到测试底板上。
    translate([-pico_center_x, -typec_shell_center_y, test_plate_t - typec_shell_local_z0])
      typec_locator_seat();

    // 口面参考薄片：打印出来可肉眼确认哪个方向朝外壳 Type-C 开孔。
    add_box(typec_open_w, 0.50, 0.80,
            0,
            pico_usb_side_y * (test_plate_h/2 - 1.00),
            test_plate_t);
  }
}

// ---------- 导出选择 ----------
if (part == "print_plate") {
  print_plate();
} else if (part == "front_shell") {
  front_shell();
} else if (part == "back_cover") {
  back_cover();
} else if (part == "pico_pair_clamp_cover") {
  pico_pair_clamp_cover();
} else if (part == "side_button_plate"
           || part == "button_plate") {
  side_button_plate_raw();
} else if (part == "typec_clamp_cover") {
  typec_clamp_cover();
} else if (part == "typec_fit_test") {
  typec_fit_test();
} else if (part == "exploded") {
  translate([0, 0, 0])
    front_shell();

  translate([0, 0, 28])
    back_cover();

  // 侧按键压板沿 X 方向向壳内侧分离，方便检查安装关系。
  translate([-8, 0, 0])
    side_button_plate_installed();

  screen_reference();
} else {
  color([0.86, 0.86, 0.86, 1.0])
    front_shell();

  color([0.70, 0.70, 0.70, 0.85])
    assembled_back_cover();

  color([0.55, 0.55, 0.55, 0.85])
    assembled_pico_pair_clamp_covers();

  color([0.62, 0.62, 0.62, 0.88])
    side_button_plate_installed();

  side_button_switch_references();
  screen_reference();
  pico_reference();

  // Type-C 开孔参考。
  color([1.0, 0.20, 0.10, 0.45])
    side_typec_cut(typec_open_w, typec_open_h,
                   1.80, typec_open_r,
                   typec_open_x, typec_open_y,
                   typec_open_center_z);
}
