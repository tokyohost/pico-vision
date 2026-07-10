/*
  2.4寸 ST7789 240x320 TFT + Raspberry Pi Pico 外壳
  单位：mm

  本文件以已经验证的 2寸版本为结构底稿，仅把屏幕和前壳尺寸替换为 2.4寸参数。
  因此后盖不是旧的双尾孔方案，而是完整保留以下结构：
    1. 四个 M2 PCB 固定螺柱；
    2. 上下两组独立 PCB 小压盖；
    3. Type-C 端左右两个侧向限位块；
    4. 非 Type-C 端一条横向限位挡板；
    5. 后盖弧形定位凸点、前壳浅凹窝和胶合台阶；
    6. 后盖非 Type-C 一侧新增 3 个 6x6x7.3 方头轻触开关；
    7. 配套键帽按图纸调整为：外径 φ8、导向套 φ5.6、总高 4mm；
    8. 后盖改为 3 个 φ6.1 键帽导向孔，不再直接让 2.4mm 开关方头穿壳；
    9. 保留 3 组开关限位、2 个 M2 螺柱和 1 块按键压盖。

  2.4寸屏幕参数：
    - PCB 外形：42.72 x 70.30 x 1.20
    - 安装孔中心距：37.72 x 65.30
    - 安装孔径：2.10
    - 有效显示区：37.42 x 49.66
    - 正面开窗：39.02 x 51.86，Y 偏移 -3.00

  Pico 参数和后盖固定结构保持 2寸版本不变。

  part 可选：
    "print_plate"：前壳、后盖和两块 PCB 小压盖同板打印
    "front_shell"：只导出前壳
    "back_cover"：只导出后盖
    "pico_pair_clamp_cover"：只导出一块 PCB 小压盖
    "button_plate"：只导出三按键共用压盖
    "assembly"：装配预览
    "exploded"：爆炸预览
*/

$fn = 56;
part = "print_plate";    // 可选："print_plate", "front_shell", "back_cover", "pico_pair_clamp_cover", "button_plate", "typec_clamp_cover", "typec_fit_test", "assembly", "exploded"

// ---------- 打印与装配余量 ----------
wall = 1.80;               // 外壳侧壁厚度
front_thick = 2.00;        // 前面板厚度
corner_r = 3.20;           // 外壳圆角
fit_clearance = 0.40;      // 屏幕 PCB 定位槽总余量，约等于单边 0.20
cover_clearance = 0.40;    // 后盖落入台阶的总余量，约等于单边 0.20
plate_gap = 12.00;         // 同板打印时两个零件之间的间距

// ---------- 2.4寸屏幕模块 ----------
screen_pcb_w = 42.72;
screen_pcb_h = 70.30;
screen_pcb_t = 1.20;
screen_hole_d = 2.10;

// 四个屏幕安装孔中心距。
screen_hole_dx = 37.72;
screen_hole_dy = 65.30;
screen_hole_edge_x = (screen_pcb_w - screen_hole_dx) / 2;
screen_hole_edge_y = (screen_pcb_h - screen_hole_dy) / 2;

// 2.4寸屏幕有效显示区。
screen_aa_w = 37.42;
screen_aa_h = 49.66;
screen_aa_y_offset = -3.00;

// 为兼容前壳内侧避让模块，将 BL 参考区设置为开窗附近尺寸。
// 这只用于前面板内侧浅避让，不改变屏幕 PCB 和螺柱位置。
screen_bl_w = screen_aa_w + 1.60;
screen_bl_h = screen_aa_h + 2.20;
screen_bl_y_offset = screen_aa_y_offset;

// 正面开窗比有效显示区略大，避免打印误差遮挡像素。
screen_window_use_bl = false;
screen_window_expand_w = 1.60;
screen_window_expand_h = 2.20;
screen_window_y_extra_tune = 0.00;
screen_window_w = screen_aa_w + screen_window_expand_w;
screen_window_h = screen_aa_h + screen_window_expand_h;
screen_window_y_offset = screen_aa_y_offset + screen_window_y_extra_tune;
screen_window_r = 1.20;

// 前面板内侧浅避让槽。
screen_bl_relief_w = screen_bl_w + 0.80;
screen_bl_relief_h = screen_bl_h + 0.80;
screen_bl_relief_depth = 0.80;
screen_bl_relief_r = 1.20;

// 屏幕从后侧通过四颗 M2 螺丝固定到前壳。
screen_boss_od = 4.70;
screen_support_h = 3.00;
screen_boss_h = 3.00;
screen_boss_pilot_d = 1.55;
screen_pilot_bottom_skin = 0.20;
screen_thread_depth_actual = min(screen_boss_h, front_thick + screen_support_h - screen_pilot_bottom_skin);

// 屏幕 PCB 四周定位边。
screen_lip_t = 1.20;
screen_lip_h = screen_support_h + 1.10;

// ---------- 2.4寸外壳尺寸 ----------
body_w = 47.20;
body_h = 76.20;
shell_depth = 18.00;

echo(str("校验：2.4寸屏幕PCB=", screen_pcb_w, " x ", screen_pcb_h,
         "mm；孔中心距=", screen_hole_dx, " x ", screen_hole_dy,
         "mm；开窗=", screen_window_w, " x ", screen_window_h,
         "mm；Y偏移=", screen_window_y_offset, "mm"));

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


// ---------- 后盖三按键：6x6x7.3 方头轻触开关 + φ8 配套键帽 ----------
// 按你提供的图纸建模：
//   - 开关塑料本体：6.0 x 6.0 x 3.1mm
//   - 方形按帽：2.4 x 2.4mm
//   - 按帽从本体顶面伸出约 4.2mm
//   - 四个引脚推荐孔中心距：X=6.5mm，Y=4.5mm，图纸孔径 φ1.15
//
// 安装方向：
//   - 开关方形按帽朝后盖外侧，并穿过后盖上的圆角方孔。
//   - 6x6 本体贴在后盖内表面，由后盖上的限位框限制 XY 位移。
//   - 一块独立压盖从内侧压住三个开关本体；引脚穿过压盖上的小孔。
//   - 两个 M2 螺柱与三个按键位于同一中心线上，压紧受力更均匀。
enable_rear_buttons = true;

// 按键放在非 Type-C 的 +Y 短边区域，避开 Pico、Type-C 和尾部横向挡板。
button_center_x = 0.00;
button_center_y = 27.00;
button_pitch_x = 10.50;

// ---------- 轻触开关方头和配套键帽 ----------
// 轻触开关图纸：本体顶面到方头顶部约 4.2mm，方头约 2.4 x 2.4mm。
// 这些参数仅用于装配预览，后盖开孔不再按 2.4mm 方头设计。
button_cap_nominal_w = 2.40;
button_cap_nominal_h = 2.40;
button_actuator_total_h = 4.20;
button_cap_z = 1.80;
button_stem_w = 1.60;
button_stem_z = 1.40;
button_collar_z = button_actuator_total_h - button_cap_z - button_stem_z; // 约 1.0mm

// 配套键帽图纸尺寸：
//   - 外圆帽直径：φ8
//   - 下部导向套直径：φ5.6
//   - 总高度：4mm
//   - 外圆帽主体高度：3mm
//   - 下部导向套伸入后盖约 1mm
//   - 中央方孔参考：约 2.15~2.45mm，与 2.4mm 方头压配
button_keycap_outer_d = 8.00;
button_keycap_guide_d = 5.60;
button_keycap_total_h = 4.00;
button_keycap_head_h = 3.00;
button_keycap_guide_h = button_keycap_total_h - button_keycap_head_h; // 1.00mm
button_keycap_socket_min = 2.15;
button_keycap_socket_max = 2.45;

// 后盖只让 φ5.6 导向套穿过，φ8 外圆帽留在外侧。
// φ6.1 等于单边留 0.25mm，给按键 0.3±0.1mm 行程和 FDM 收缩留余量。
// 若实际打印孔偏小，可调到 6.20~6.30；若键帽晃动较大，可减到 6.00。
button_keycap_hole_d = 6.10;
button_keycap_hole_z_extra = 0.30;

// 外表面入口再放宽一点并做 0.35mm 浅导入口，避免首层毛边刮住键帽导向套。
// 这不是 φ8 键帽沉孔，φ8 圆帽仍完整露在后盖外侧。
button_keycap_entry_d = 6.50;
button_keycap_entry_depth = 0.35;

// 几何校验：开关方头露出后盖约 2mm；键帽下部导向套可进入孔内约 1mm。
button_switch_exposed_h = button_actuator_total_h - cover_t;
button_keycap_edge_gap = button_pitch_x - button_keycap_outer_d;

// 6x6 开关本体限位框，只限制 XY，不挤压开关。
button_switch_body_w = 6.00;
button_switch_body_h = 6.00;
button_switch_body_z = 3.10;
button_switch_fit_clearance = 0.25; // 单边间隙
button_switch_limit_t = 0.90;       // 适合 0.4mm 喷嘴，约两道线宽
button_switch_limit_h = 1.80;       // 低于 3.1mm 本体，避免干涉引脚

// 两个按键压盖 M2 螺柱。
button_post_x = 18.00;
button_post_y = button_center_y;
button_post_od = 4.80;
button_post_pilot_d = 1.55;

// 螺柱顶部比开关本体背面低 0.08mm，锁紧后压盖会轻压开关。
// 打印误差较大或按键过紧，可将 button_clamp_preload 改为 0。
button_clamp_preload = 0.08;
button_post_h = button_switch_body_z - button_clamp_preload;
// 配合 1.8mm 压盖建议先试 M2x5 自攻螺丝；不要直接使用过长螺丝，以免顶穿后盖。

// 三个开关共用的一块压盖。
button_plate_w = 44.00;
button_plate_h = 12.00;
button_plate_t = 1.80;
button_plate_r = 1.50;
button_plate_screw_clear_d = 2.40;
button_plate_head_d = 4.40;
button_plate_head_depth = 0.75;

// 图纸推荐 PCB 孔位：6.5 x 4.5，φ1.15。
// 给 FDM 小孔增加打印余量，默认使用 φ1.35。
button_pin_dx = 6.50;
button_pin_dy = 4.50;
button_pin_hole_d = 1.35;
button_center_relief_d = 2.80;

// 位置和边界校验。
button_locator_outer_half_w =
    (button_switch_body_w + 2*button_switch_fit_clearance)/2 + button_switch_limit_t;
button_locator_outer_half_h =
    (button_switch_body_h + 2*button_switch_fit_clearance)/2 + button_switch_limit_t;

echo(str("校验：三按键中心=(", button_center_x, ", ", button_center_y,
         ")mm；横向间距=", button_pitch_x, "mm；键帽导向孔=φ",
         button_keycap_hole_d, "mm；外圆帽=φ", button_keycap_outer_d, "mm"));
echo(str("校验：键帽下导向套=φ", button_keycap_guide_d,
         " x ", button_keycap_guide_h, "mm；相邻键帽边缘间隙=",
         button_keycap_edge_gap, "mm；开关方头理论露出后盖=",
         button_switch_exposed_h, "mm"));
echo(str("校验：开关本体=6 x 6 x ", button_switch_body_z,
         "mm；按键压盖=", button_plate_w, " x ", button_plate_h,
         " x ", button_plate_t, "mm；压盖螺柱X=±", button_post_x, "mm"));
echo(str("校验：按键区域最外侧X=",
         button_pitch_x + button_locator_outer_half_w,
         "mm；Y范围=", button_center_y - button_locator_outer_half_h,
         "~", button_center_y + button_locator_outer_half_h,
         "mm；后盖半宽=", cover_w/2, "mm；半高=", cover_h/2, "mm"));

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


// ---------- 三按键定位、键帽圆孔和独立压盖模块 ----------
module at_rear_button_positions() {
  if (enable_rear_buttons)
    for (x_offset = [-button_pitch_x, 0, button_pitch_x])
      translate([button_center_x + x_offset, button_center_y, 0])
        children();
}

module at_button_plate_positions() {
  if (enable_rear_buttons)
    for (x_offset = [-button_pitch_x, 0, button_pitch_x])
      translate([x_offset, 0, 0])
        children();
}

module at_button_post_positions() {
  if (enable_rear_buttons)
    for (sx = [-1, 1])
      translate([button_center_x + sx*button_post_x, button_post_y, 0])
        children();
}

module at_button_plate_screw_positions() {
  if (enable_rear_buttons)
    for (sx = [-1, 1])
      translate([sx*button_post_x, 0, 0])
        children();
}

module rear_button_cap_hole_cuts() {
  // 配套键帽的 φ5.6 下导向套穿过后盖，因此这里改成圆孔。
  // 主贯穿孔默认 φ6.1，保证键帽在 0.3±0.1mm 按压行程中不会卡住。
  at_rear_button_positions() {
    translate([0, 0, -button_keycap_hole_z_extra])
      cylinder(d = button_keycap_hole_d,
               h = cover_t + 2*button_keycap_hole_z_extra);

    // 后盖外表面浅导入口，只消除孔口锐边和首层毛边。
    // φ8 外圆帽不会进入这个孔，仍由后盖外表面承托。
    translate([0, 0, -0.05])
      cylinder(d = button_keycap_entry_d,
               h = button_keycap_entry_depth + 0.05);
  }
}

module tactile_switch_locator_one() {
  // 6x6 开关本体贴在后盖内表面。
  // 四条低矮限位筋只控制平面位置，不顶住开关引脚。
  inner_w = button_switch_body_w + 2*button_switch_fit_clearance;
  inner_h = button_switch_body_h + 2*button_switch_fit_clearance;
  t = button_switch_limit_t;
  h = button_switch_limit_h;

  // 左右限位筋。
  add_box(t, inner_h + 2*t, h,
          -inner_w/2 - t/2, 0, cover_t);
  add_box(t, inner_h + 2*t, h,
           inner_w/2 + t/2, 0, cover_t);

  // 上下限位筋。
  add_box(inner_w, t, h,
          0, -inner_h/2 - t/2, cover_t);
  add_box(inner_w, t, h,
          0,  inner_h/2 + t/2, cover_t);
}

module rear_button_switch_locators() {
  at_rear_button_positions()
    tactile_switch_locator_one();
}

module rear_button_posts() {
  // 两个 M2 螺柱与三枚按键共线，压盖锁紧后不易单边翘起。
  at_button_post_positions()
    translate([0, 0, cover_t])
      cylinder(d = button_post_od, h = button_post_h);
}

module rear_button_post_hole_cuts() {
  // M2 自攻底孔从螺柱内部向上切，后盖外表面保持封闭。
  at_button_post_positions()
    translate([0, 0, cover_t + 0.30])
      cylinder(d = button_post_pilot_d,
               h = button_post_h + 0.30);
}

module button_plate_raw() {
  // 独立按键压盖：一块板同时压住三个 6x6 开关。
  // 四个引脚孔采用图纸推荐的 6.5 x 4.5mm 中心距。
  difference() {
    rounded_prism(button_plate_w,
                  button_plate_h,
                  button_plate_t,
                  button_plate_r);

    // 两个 M2 通孔。
    at_button_plate_screw_positions()
      translate([0, 0, -0.30])
        cylinder(d = button_plate_screw_clear_d,
                 h = button_plate_t + 0.60);

    // M2 螺丝头浅沉孔。
    at_button_plate_screw_positions()
      translate([0, 0, button_plate_t - button_plate_head_depth])
        cylinder(d = button_plate_head_d,
                 h = button_plate_head_depth + 0.30);

    // 每个开关对应四个引脚孔和一个中央避让孔。
    at_button_plate_positions() {
      for (px = [-button_pin_dx/2, button_pin_dx/2])
        for (py = [-button_pin_dy/2, button_pin_dy/2])
          translate([px, py, -0.30])
            cylinder(d = button_pin_hole_d,
                     h = button_plate_t + 0.60);

      translate([0, 0, -0.30])
        cylinder(d = button_center_relief_d,
                 h = button_plate_t + 0.60);
    }
  }
}

module button_plate_installed_local() {
  // 后盖局部坐标中的装配位置：压盖底面落在两个螺柱顶部。
  translate([button_center_x,
             button_center_y,
             cover_t + button_post_h])
    button_plate_raw();
}

module rear_button_switch_reference_local() {
  // 装配预览参考：
  //   - 6x6x3.1 开关本体贴后盖内表面；
  //   - 2.4mm 方头朝外；
  //   - φ8 配套键帽套在方头上，φ5.6 导向套进入后盖圆孔约 1mm。
  if (enable_rear_buttons)
    at_rear_button_positions() {
      // 6x6x3.1 塑料本体。
      color([0.12, 0.12, 0.12, 0.55])
        translate([0, 0, cover_t + button_switch_body_z/2])
          cube([button_switch_body_w,
                button_switch_body_h,
                button_switch_body_z],
               center = true);

      // 开关本身的圆形基座、方柄和 2.4mm 方头。
      color([0.14, 0.14, 0.14, 0.65])
        translate([0, 0, cover_t - button_collar_z/2])
          cylinder(d = 3.20, h = button_collar_z, center = true);

      color([0.08, 0.08, 0.08, 0.70])
        translate([0, 0,
                   cover_t - button_collar_z - button_stem_z/2])
          cube([button_stem_w,
                button_stem_w,
                button_stem_z],
               center = true);

      color([0.02, 0.02, 0.02, 0.80])
        translate([0, 0,
                   cover_t - button_collar_z - button_stem_z - button_cap_z/2])
          cube([button_cap_nominal_w,
                button_cap_nominal_h,
                button_cap_z],
               center = true);

      // 购买的配套键帽参考：
      // φ8 主帽位于后盖外侧，高 3mm；φ5.6 导向套向壳内伸入 1mm。
      color([0.05, 0.05, 0.05, 0.82])
        translate([0, 0, -button_keycap_head_h])
          cylinder(d = button_keycap_outer_d,
                   h = button_keycap_head_h);

      color([0.08, 0.08, 0.08, 0.72])
        translate([0, 0, 0])
          cylinder(d = button_keycap_guide_d,
                   h = button_keycap_guide_h);
    }
}

module assembled_button_plate() {
  // 与后盖采用同样的 Y 轴翻转，保证压盖在最终装配中的方向正确。
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      button_plate_installed_local();
}

module assembled_button_switch_references() {
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      rear_button_switch_reference_local();
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

      // 屏幕四个 M2 支撑台，中心距按 2.4寸屏幕的 37.72 x 65.30 放置。
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
  // 按你上传的 SVG 草图重新设计：
  //   - 4 个圆形 M2 螺柱位于 PCB 两侧，由两块小压盖跨过 PCB 锁紧
  //   - 非 Type-C 端 1 条横向挡板，距离 Type-C 口所在短边 54mm
  //   - 不再新增螺柱；原 4 个螺柱按上下两组各锁一块小盖板，一共 2 个小盖板
  //   - Type-C 端 2 个侧向定位块，只限制左右位移，不做口前横向挡板
  //   - 左右两组螺柱中心距 26mm，避免 20.50mm 宽 PCB 压住螺丝孔
  //   - 后盖四周保留原来的弧形小凸点卡扣，配合前壳浅凹窝定位
  // 整个结构只接触 PCB 平整背面和板边，不去压 Type-C 那一面的电子元件。
  difference() {
    union() {
      rounded_prism(cover_w, cover_h, cover_t, max(0.10, corner_r - rear_edge_wall - cover_clearance/2));

      // 原后盖四周的小凸起卡扣，上一版漏加了，这里恢复。
      rear_cover_arc_detents();

      // PCB 固定和辅助定位结构。
      pico_svg_mount_features();

      // 三个 6x6 按键本体的后盖限位框。
      rear_button_switch_locators();

      // 三按键共用压盖的两个 M2 螺柱。
      rear_button_posts();
    }

    // 四个 Pico 小压盖固定螺柱的 M2 自攻底孔。
    pico_svg_mount_boss_holes();

    // 后盖上的三个 φ6.1 键帽导向孔，并在外侧增加 φ6.5 浅导入口。
    rear_button_cap_hole_cuts();

    // 两个按键压盖螺柱的 M2 自攻底孔。
    rear_button_post_hole_cuts();

    // Pico 小压盖使用原 4 个 PCB 螺柱，不需要额外底孔。
  }
}

// ---------- 同平面打印布局 ----------
module print_plate() {
  // 左边前壳，屏幕面贴打印平台；右边后盖，外侧贴打印平台。
  // 已移除 Type-C 独立压盖小件的同板打印输出。
  translate([-(body_w/2 + plate_gap/2), 0, 0])
    front_shell();

  translate([(cover_w/2 + plate_gap/2), 0, 0])
    back_cover();

  // 两个 PCB 小压盖，使用原 4 个 PCB 螺柱，两块同板打印。
  // 放在后盖下方纵向排列，避免和前壳、后盖重叠。
  translate([(cover_w/2 + plate_gap/2),
             -(cover_h/2 + pico_pair_clamp_cover_h/2 + plate_gap/2), 0])
    pico_pair_clamp_cover();

  translate([(cover_w/2 + plate_gap/2),
             -(cover_h/2 + pico_pair_clamp_cover_h*1.5 + plate_gap/2 + 3.00), 0])
    pico_pair_clamp_cover();

  // 三个后盖按键共用的一块独立压盖，放在前壳下方。
  translate([-(body_w/2 + plate_gap/2),
             -(body_h/2 + button_plate_h/2 + plate_gap/2), 0])
    button_plate_raw();
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

  // 四个屏幕螺丝孔参考点：装配预览时用于核对 37.72 x 65.30 孔距。
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
} else if (part == "button_plate") {
  button_plate_raw();
} else if (part == "typec_clamp_cover") {
  typec_clamp_cover();
} else if (part == "typec_fit_test") {
  typec_fit_test();
} else if (part == "exploded") {
  translate([0, 0, 0]) front_shell();
  translate([0, 0, 27]) back_cover();
  translate([0, 0, 27]) button_plate_installed_local();
  translate([0, 0, 0]) screen_reference();
} else {
  color([0.86, 0.86, 0.86, 1.0]) front_shell();
  color([0.70, 0.70, 0.70, 0.85]) assembled_back_cover();
  color([0.55, 0.55, 0.55, 0.85]) assembled_pico_pair_clamp_covers();
  color([0.62, 0.62, 0.62, 0.88]) assembled_button_plate();
  assembled_button_switch_references();
  screen_reference();
  pico_reference();

  // Type-C 开孔参考。
  color([1.0, 0.20, 0.10, 0.45])
    side_typec_cut(typec_open_w, typec_open_h, 1.80, typec_open_r,
                   typec_open_x, typec_open_y, typec_open_center_z);
}
