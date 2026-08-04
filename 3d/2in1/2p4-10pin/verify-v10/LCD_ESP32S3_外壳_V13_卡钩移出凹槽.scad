/*
  2.4寸 ST7789 240x320 IPS 插接 10Pin 裸屏 + ESP32-S3 双Type-C主板外壳
  单位：mm

  V13修正：屏幕凹槽向FPC侧移动1.00mm后，盖板卡钩仍停留在旧基准，卡钩根部侵入LCD凹槽；
  本版将两枚卡钩根部同步移到新凹槽外侧，和凹槽边缘保留0.30mm净距，并向短边内壁搭接0.30mm；
  同时增加LCD凹槽高度范围的最终保护切除，防止布尔合并或打印误差再次在凹槽内形成凸起。

  V12修正：删除屏幕异形盖板底面的四个圆形压屏凸点，盖板底面改为完整平面，便于直接平放3D打印；
  盖板安装高度同步下移0.30mm，底面与屏幕后壳之间保留0.25mm间隙，建议整面贴0.20~0.30mm EVA泡棉；
  FPC转接PCB顶部的四根φ1.90mm限位柱继续保留，不属于本次删除范围。

  V11修正：取消ESP32 Type-C侧EVA横压板底部0.30mm凸台，横压板底面改为完整平面；
  同时将横压板安装高度下移0.30mm，1.0mm EVA理论压缩量仍保持约0.10mm。

  V10修正：正面每个触点改为两段重叠的T形焊盘：0.90x1.00mm图纸接触段 + 1.30x1.30mm外露补焊段；外侧实际露铜约1.00mm。
  F.Mask对两段均明确开窗，F.Paste只保留图纸接触段；背面GND/K1/K2/K3焊盘继续保留。PCB仍为26x9.1mm。
  FPC转接PCB仍为20x30mm，20mm短边朝FPC端；四孔柱距X=15.00mm、Y=18.80mm。

  本版将裸屏固定方式改为“对侧插入式盖板卡钩 + 原螺丝侧双 M2 锁紧”。
  V4 同步适配新的 20 x 30mm FPC 转接 PCB 四孔布局：
    1. 裸屏主体：42.72±0.15 x 58.80±0.15 x 2.20mm；
    2. VA 有效显示区：37.42 x 49.66mm，距屏幕上边约 2.65mm；
    3. 保留 43.22 x 59.30mm 浅凹槽，裸屏正面嵌入 0.70mm；
    4. 凹槽四周继续向后抬高 1.20mm，形成约 1.90mm 总侧向限位；
    5. 保留原有 +Y 侧两颗 M2 螺柱，不改变螺丝侧位置；
    6. 盖板延伸到 -Y 对侧，左右两枚插片先插入固定卡槽；
    7. 盖板右侧不再为按键开缺口；FPC端中央继续镂空排线折弯区；
    8. 盖板中间保持完整实心，不再设置中央减重/散热镂空；
    9. 从 FPC 侧卡扣边缘向屏幕中心 23.50mm 设置 FPC 小板固定位；
    10. FPC 转接 PCB 改为 20.00 x 30.00mm、四个 φ2.20mm 固定孔；盖板改用四根 φ1.90mm 无孔实心限位柱；20mm 短边朝 FPC，原两柱对应靠 FPC 的 PCB y=8.70mm 那一排；
    11. 屏幕盖板底面取消四个圆形压屏凸点，改为完整平面；底面预留0.25mm，建议整面贴0.20~0.30mm EVA泡棉；
    12. FPC 根部避让槽高度缩至 3.60mm，排线折向后盖方向；
    13. 屏幕凹槽与裸屏在原向 FPC 侧偏移 1.92mm 的基础上再移动 1.00mm，总偏移 2.92mm；正面开窗保持原位，用于修正约 2mm 的左右黑边差；
    14. 外壳外形缩为 50.00 x 72.40 x 18.00mm；
    15. 50.40mm 高的开窗在 72.40mm 外壳上形成上下各约 11.00mm 的等宽边框；
    16. Pico、Type-C、Type-C对侧三按键和后盖结构按新外壳高度自动重算；
    17. 三按键位于Type-C对侧（+Y短边）；改用26x9.1x1.6mm紧凑PCB、两颗M2固定，开关横向中心距5.60mm；
    18. 取消后盖 PCB 尾部两颗固定螺柱及两块 L 形小压盖，仅保留 Type-C 侧双螺柱 EVA 横压板；
    19. 卡槽根部加宽到8.00mm、扣唇加厚到1.20mm、有效搭接增加到1.80mm；
    20. 卡钩为固定钩，不依赖反复弯折，PLA/PETG均可打印；
    21. TS-C005总高4.30mm，Type-C对侧短边开3个φ2.60mm通孔并做φ3.40x0.50mm浅凹；按钮顶端约高出外表面0.80mm，无键帽；为PCB背面M2螺丝头与ESP32模组尾端留出装配空间；
    22. FPC侧两枚盖板卡钩根部跟随实际屏幕凹槽移动，根部完全退出LCD凹槽，并与凹槽边缘保留0.30mm净距。

  装屏顺序：
    - 先将裸屏平放入凹槽，FPC 向后盖方向预折；
    - 将盖板 -Y 端的两枚插片推入对侧卡槽；
    - 确认FPC从中央缺口穿出；按键PCB位于+Y短边并避开屏幕压板；
    - 最后放下 +Y 螺丝侧，用两颗 M2 均匀轻锁。

  坐标方向：
    X = 屏幕宽度方向，三枚按键沿X横向排列；
    Y = 屏幕高度方向，+Y 为Type-C对侧按键所在短边，-Y 为双Type-C/FPC侧；
    Z = 前面板外表面指向后盖。

  part 可选：
    "print_plate"：前壳、后盖、屏幕异形盖板和ESP32 EVA横压板同板打印（按键PCB不参与3D打印）
    "front_shell"：只导出带加深凹槽、对侧卡槽和原螺丝侧双螺柱的前壳
    "screen_clamp_bar"：只导出屏幕异形盖板
    "screen_x_backplate"：兼容旧名称，同样导出屏幕异形盖板
    "back_cover"：只导出后盖
    "esp32_usb_clamp_bar"：只导出 Type-C 后方的 ESP32 EVA 横压板
    "side_button_pcb_reference"：只显示26x9.1mm三按键PCB、正面12个T形露铜焊盘与背面焊线盘装配参考
    "side_button_plate" / "button_plate"：兼容旧名称，改为显示按键PCB参考（不可作为塑料压板打印）
    "typec_clamp_cover"：只导出 Type-C 独立压盖
    "typec_fit_test"：只导出 Type-C 限位测试块
    "assembly"：装配预览
    "exploded"：爆炸预览
*/

$fn = 56;
part = "print_plate";    // 可选："print_plate", "front_shell", "screen_clamp_bar", "screen_x_backplate", "back_cover", "esp32_usb_clamp_bar", "side_button_pcb_reference", "typec_clamp_cover", "typec_fit_test", "assembly", "exploded"

// ---------- 打印与装配余量 ----------
wall = 1.80;               // 外壳侧壁厚度
front_thick = 2.00;        // 前面板厚度
corner_r = 3.20;           // 外壳圆角
fit_clearance = 0.50;      // 裸屏凹槽总装配余量；对应单边 0.25mm
cover_clearance = 0.40;    // 后盖落入台阶的总余量，约等于单边 0.20
plate_gap = 12.00;         // 同板打印时两个零件之间的间距

// ---------- 2.4寸插接 10Pin 裸屏：42.72 x 58.80mm ----------
// 图纸正面主体尺寸。
screen_body_w = 42.72;
screen_body_h = 58.80;
screen_body_t = 2.20;
screen_body_tol = 0.15;
screen_body_w_max = screen_body_w + screen_body_tol;
screen_body_h_max = screen_body_h + screen_body_tol;

// 图纸内部显示框和 VA。
screen_view_w = 40.62;
screen_aa_w = 37.42;
screen_aa_h = 49.66;
screen_aa_top_from_body = 2.65;
screen_aa_y_offset =
    screen_body_h/2
    - (screen_aa_top_from_body + screen_aa_h/2); // +1.92

// 原设计：裸屏安装中心向 FPC(-Y)侧偏移 1.92mm，使 VA 中心落在外壳 Y=0。
// 本次实物修正：四周屏幕凹槽与裸屏继续向 FPC 卡扣侧移动 1.00mm。
// 正面开窗和+Y侧螺柱基准保持不动；-Y侧盖板卡钩在V13中改为跟随实际凹槽边缘。
screen_mount_base_y = -screen_aa_y_offset;     // -1.92，原固定结构/开窗基准
screen_recess_shift_to_fpc = -1.00;            // 实物修正：向 FPC(-Y)侧再移 1.00mm
screen_mount_y =
    screen_mount_base_y + screen_recess_shift_to_fpc; // -2.92，裸屏与四周凹槽中心
screen_fixing_y = screen_mount_base_y;         // -1.92，保留给开窗/FPC槽/+Y螺柱等旧基准

// 前盖可视开窗：略大于 VA，但不露出过多黑边。
screen_window_clearance_w = 1.18;
screen_window_clearance_h = 0.74;
screen_window_w = screen_aa_w + screen_window_clearance_w; // 38.60
screen_window_h = screen_aa_h + screen_window_clearance_h; // 50.40
screen_window_y_extra_tune = 0.00;
screen_window_y_offset =
    screen_mount_base_y + screen_aa_y_offset + screen_window_y_extra_tune; // 0.00，开窗保持原位
screen_va_center_y = screen_mount_y + screen_aa_y_offset;            // -1.00
screen_va_to_window_y = screen_va_center_y - screen_window_y_offset; // -1.00，VA相对开窗向FPC侧偏移
screen_window_r = 1.00;

// 前盖内侧裸屏凹槽。
// 裸屏正面嵌入前盖 0.70mm，凹槽周围形成完整承托肩位。
screen_recess_clearance = fit_clearance; // 总余量 0.50mm，单边 0.25mm
screen_recess_w = screen_body_w + screen_recess_clearance;
screen_recess_h = screen_body_h + screen_recess_clearance;
screen_recess_depth = 0.70;
screen_recess_r = 0.80;
screen_front_z = front_thick - screen_recess_depth;
screen_back_z = screen_front_z + screen_body_t;

// 凹槽四周向后盖方向继续抬高，形成更深的屏幕侧向限位。
enable_screen_recess_guide = true;
screen_recess_guide_h = 1.20;
screen_recess_guide_t = 1.00;
screen_recess_guide_lead = 0.30;
screen_recess_guide_fpc_extra = 1.00;
screen_recess_total_limit_depth =
    screen_recess_depth + screen_recess_guide_h;
screen_recess_guide_outer_w =
    screen_recess_w + 2*screen_recess_guide_t;
screen_recess_guide_outer_h =
    screen_recess_h + 2*screen_recess_guide_t;

// FPC 图纸参考与 -Y 侧弯折避让。
screen_total_h = 82.30;
screen_fpc_extension_h = screen_total_h - screen_body_h;
screen_fpc_root_w = 19.60;
screen_fpc_tail_w = 11.00;
screen_fpc_contact_h = 5.00;
screen_fpc_pitch = 0.50;
screen_fpc_pin_count = 10;
screen_fpc_t = 0.30;
screen_fpc_exit_w = screen_fpc_root_w + 0.80; // 20.40
screen_fpc_exit_h = 3.60;                    // FPC 可折，缩短外壳后只保留根部弯折空间
screen_fpc_exit_inner_offset = 0.60;          // 避让槽向屏幕内部重叠，保住外框厚度
screen_fpc_exit_r = 0.80;
screen_recess_guide_fpc_w =
    screen_fpc_exit_w + screen_recess_guide_fpc_extra;
// FPC 前框避让槽保持原位置，不随凹槽继续外移，避免 FPC 侧前框仅剩约 0.63mm。
// 凹槽移动后，避让槽与屏幕根部的内侧重叠由 0.60mm 增至约 1.60mm，仍可顺利折弯。
screen_fpc_channel_center_y =
    screen_fixing_y
    - screen_recess_h/2
    - screen_fpc_exit_h/2
    + screen_fpc_exit_inner_offset;

// 外壳缩短后，50.40mm 高的开窗位于中心，两边框各约 11.00mm。
body_w = 50.00;
body_h = 72.40;
shell_depth = 18.00;

// 三按键整体向 PCB 尾部（+Y）平移，屏幕盖板避让缺口与按键机构共用此基准。
side_button_shift_to_tail = 5.00;

// ---------- 屏幕固定：FPC侧固定卡钩 + 对侧双 M2 螺柱直条压板 ----------
enable_screen_single_side_mount = true;

// +Y 非 FPC 侧保留两个 M2 螺柱。
screen_clamp_screw_dx = 34.00;
screen_clamp_screw_y_offset = 32.70;
screen_clamp_screw_y = screen_fixing_y + screen_clamp_screw_y_offset;
screen_boss_od = 5.00;
screen_boss_base_od = 5.60;
screen_boss_base_h = 0.85;
screen_boss_embed = 0.60;
screen_boss_pilot_d = 1.60;

// -Y 对侧两个加强盖板卡槽。
// V13：卡钩根部不能再使用旧的 screen_fixing_y，否则会侵入已向FPC侧移动1.00mm的新凹槽。
// 根部内侧面以实际凹槽 -Y 边缘为基准，再向短边外侧退出0.30mm；
// 根部外侧直接与短边内壁搭接0.30mm，消除原先难打印的薄缝。
screen_hook_x = 16.00;
screen_hook_w = 7.00;
screen_hook_root_w = 8.00;
screen_hook_overhang = 2.00;
screen_hook_clearance = 0.15;
screen_hook_lip_t = 1.20;
screen_hook_lead = 0.35;
screen_hook_recess_clearance = 0.30;
screen_hook_wall_overlap = 0.30;
screen_hook_recess_edge_y = screen_mount_y - screen_recess_h/2;
screen_hook_inner_y =
    screen_hook_recess_edge_y - screen_hook_recess_clearance;
screen_hook_base_outer_y =
    -(body_h - 2*wall)/2 - screen_hook_wall_overlap;
screen_hook_base_t =
    screen_hook_inner_y - screen_hook_base_outer_y;

// 最终LCD凹槽保护切除：只清理屏幕本体高度范围，不碰上方扣唇。
screen_lcd_keepout_xy_clearance = 0.10;
screen_lcd_keepout_top_extra = 0.15;

// 独立异形屏幕盖板。原 +Y 侧螺丝位置不变，盖板一直延伸到 -Y 对侧卡槽。
// 宽度略小于凹槽，避免装配时擦到左右限位围边。
screen_clamp_bar_w = screen_recess_w - 1.20; // 42.02
screen_cover_hook_insert_clear = 0.20;
screen_cover_hook_end_y = screen_hook_inner_y + screen_cover_hook_insert_clear;
screen_cover_screw_end_y = screen_clamp_screw_y + 3.00;
screen_clamp_bar_h = screen_cover_screw_end_y - screen_cover_hook_end_y;
screen_clamp_bar_t = 1.60;
screen_clamp_bar_r = 1.00;
screen_clamp_bar_center_y =
    (screen_cover_screw_end_y + screen_cover_hook_end_y)/2;
screen_clamp_screw_local_y =
    screen_clamp_screw_y - screen_clamp_bar_center_y;
screen_clamp_screw_clear_d = 2.40;
screen_clamp_head_d = 4.40;
screen_clamp_head_depth = 0.75;

// V12：取消盖板底面的四个圆形压屏凸点，盖板改为完整平底。
// 底面与屏幕后壳保留0.25mm，用于整面粘贴0.20~0.30mm EVA泡棉。
// screen_clamp_pad_h 保留为0，仅用于兼容下方通孔/避让深度计算。
screen_cover_under_gap = 0.25;
screen_clamp_pad_h = 0.00;
screen_clamp_preload = 0.00;
screen_clamp_install_z =
    screen_back_z + screen_cover_under_gap - screen_clamp_preload;
screen_boss_z0 = front_thick - screen_boss_embed;
screen_boss_h = screen_clamp_install_z - screen_boss_z0;
screen_thread_depth_actual = screen_boss_h - screen_boss_embed;

// 卡钩底面高于盖板顶面 0.20mm，让插片能顺利推入，螺丝锁紧后再定位。
screen_hook_lip_z0 =
    screen_clamp_install_z + screen_clamp_bar_t + screen_hook_clearance;
screen_hook_top_z = screen_hook_lip_z0 + screen_hook_lip_t;

// 盖板避让：右侧三按键PCB、-FPC端排线折弯区以及中央减重散热窗。
enable_screen_cover_button_cut = false; // V6：按键已移到+Y短边，屏幕盖板右侧不再开缺口
screen_cover_button_cut_w = 5.00;
screen_cover_button_cut_h = 44.00;
screen_cover_button_cut_y = side_button_shift_to_tail; // 与向尾部平移后的三按键组中心对齐
screen_cover_fpc_cut_w = screen_fpc_exit_w + 1.60; // 22.00
screen_cover_fpc_cut_h = 8.00;
enable_screen_cover_center_relief = false; // 按要求：压板中间保持实心
screen_cover_center_relief_w = 25.00;
screen_cover_center_relief_h = 32.00;
screen_cover_center_relief_r = 2.00;

// FPC 卡口/转接 PCB 固定位。
// 新 PCB 尺寸为 20.00 x 30.00mm，左上角为原点，四个孔心：
//   (2.50, 8.70)、(17.50, 8.70)、(2.50, 27.50)、(17.50, 27.50)mm。
// 安装方向：20mm 短边朝向 FPC(-Y)端，30mm 长边沿盖板 +Y 向屏幕中心/螺丝侧延伸。
// 因此 PCB X 方向映射为盖板 X，PCB Y 方向映射为盖板 Y。
// 原来的两根限位柱保留为靠 FPC 的 y=8.70mm 那一排；
// 新增 y=27.50mm 那一排，沿盖板 +Y 方向相距 18.80mm。
screen_fpc_board_w = 20.00;
screen_fpc_board_h = 30.00;
screen_fpc_board_hole_d = 2.20;
screen_fpc_board_hole_x_left = 2.50;
screen_fpc_board_hole_x_right = 17.50;
screen_fpc_board_hole_y_near = 8.70;
screen_fpc_board_hole_y_far = 27.50;

// 靠 FPC 的 y=8.70mm 原两柱继续保持距 FPC 侧卡扣边缘 23.50mm。
screen_fpc_board_near_from_hook = 23.50;
screen_fpc_board_post_y_near =
    screen_cover_hook_end_y + screen_fpc_board_near_from_hook;
screen_fpc_board_post_y_far =
    screen_fpc_board_post_y_near
    + (screen_fpc_board_hole_y_far - screen_fpc_board_hole_y_near);

// 20mm 短边上的左右孔距为 15.00mm，以孔对中点对齐盖板 X=0，因此柱中心为 X=±7.50mm。
screen_fpc_board_post_x =
    (screen_fpc_board_hole_x_right - screen_fpc_board_hole_x_left)/2;
screen_fpc_board_post_dx = 2*screen_fpc_board_post_x;
screen_fpc_board_post_dy =
    screen_fpc_board_post_y_far - screen_fpc_board_post_y_near;

// φ2.20mm 孔采用 φ1.90mm 实心限位柱，单边理论间隙 0.15mm，适合 FDM 装配。
screen_fpc_board_post_d = 1.90;
screen_fpc_board_post_h = 3.20;
screen_fpc_board_post_radial_clearance =
    (screen_fpc_board_hole_d - screen_fpc_board_post_d)/2;

// 几何安全校验。
screen_inner_half_x = (body_w - 2*wall)/2;
screen_inner_half_y = (body_h - 2*wall)/2;

screen_recess_side_margin =
    screen_inner_half_x - screen_recess_w/2;
screen_recess_pos_y_gap =
    screen_inner_half_y - (screen_mount_y + screen_recess_h/2);
screen_recess_neg_y_gap =
    screen_inner_half_y - (-screen_mount_y + screen_recess_h/2);
screen_recess_min_y_gap =
    min(screen_recess_pos_y_gap, screen_recess_neg_y_gap);

screen_recess_guide_side_gap =
    screen_inner_half_x - screen_recess_guide_outer_w/2;
screen_recess_guide_pos_y_gap =
    screen_inner_half_y - (screen_mount_y + screen_recess_guide_outer_h/2);
screen_recess_guide_neg_y_gap =
    screen_inner_half_y - (-screen_mount_y + screen_recess_guide_outer_h/2);
screen_recess_guide_min_y_gap =
    min(screen_recess_guide_pos_y_gap, screen_recess_guide_neg_y_gap);

screen_boss_to_screen_gap =
    screen_clamp_screw_y
    - screen_boss_base_od/2
    - (screen_mount_y + screen_recess_h/2);
screen_boss_to_inner_wall_gap =
    screen_inner_half_y
    - (screen_clamp_screw_y + screen_boss_base_od/2);
screen_clamp_bar_to_inner_wall_gap =
    screen_inner_half_y
    - (screen_clamp_bar_center_y + screen_clamp_bar_h/2);
screen_cover_hook_side_wall_gap =
    screen_inner_half_y + screen_cover_hook_end_y;
screen_cover_side_wall_gap =
    screen_inner_half_x - screen_clamp_bar_w/2;
screen_cover_hook_engagement =
    screen_hook_overhang - screen_cover_hook_insert_clear;
screen_cover_fpc_to_hook_gap =
    screen_hook_x - screen_hook_w/2 - screen_cover_fpc_cut_w/2;
screen_hook_root_to_fpc_gap =
    screen_hook_x - screen_hook_root_w/2
    - screen_recess_guide_fpc_w/2;
screen_hook_root_to_side_wall_gap =
    screen_inner_half_x - (screen_hook_x + screen_hook_root_w/2);
screen_hook_root_to_recess_gap =
    screen_hook_recess_edge_y - screen_hook_inner_y;
screen_hook_root_wall_overlap_actual =
    -screen_inner_half_y - screen_hook_base_outer_y;
screen_cover_right_rail_w =
    screen_clamp_bar_w/2 - screen_cover_button_cut_w
    - screen_cover_center_relief_w/2;
screen_fpc_board_post_side_gap =
    screen_clamp_bar_w/2
    - (screen_fpc_board_post_x + screen_fpc_board_post_d/2);
screen_fpc_board_near_from_hook_actual =
    screen_fpc_board_post_y_near - screen_cover_hook_end_y;
screen_fpc_board_far_to_screw_end_gap =
    screen_cover_screw_end_y
    - (screen_fpc_board_post_y_far + screen_fpc_board_post_d/2);
screen_hook_to_fpc_gap =
    screen_hook_x - screen_hook_w/2 - screen_recess_guide_fpc_w/2;
screen_fpc_outer_frame =
    body_h/2
    + screen_fpc_channel_center_y
    - screen_fpc_exit_h/2;
screen_window_pos_y_border =
    body_h/2 - (screen_window_y_offset + screen_window_h/2);
screen_window_neg_y_border =
    body_h/2 - (-screen_window_y_offset + screen_window_h/2);

screen_clamp_bar_print_w = screen_clamp_bar_w;
screen_clamp_bar_print_h = screen_clamp_bar_h;

echo(str("校验：裸屏主体=", screen_body_w, " x ",
         screen_body_h, " x ", screen_body_t,
         "mm；最大公差=", screen_body_w_max, " x ",
         screen_body_h_max, "mm"));
echo(str("校验：VA=", screen_aa_w, " x ", screen_aa_h,
         "mm；VA相对玻璃中心Y=", screen_aa_y_offset,
         "mm；原固定件基准Y=", screen_fixing_y,
         "mm；凹槽/裸屏中心Y=", screen_mount_y,
         "mm；最终开窗中心Y=", screen_window_y_offset,
         "mm；VA相对开窗偏移Y=", screen_va_to_window_y, "mm"));
echo(str("校验：前盖开窗=", screen_window_w, " x ",
         screen_window_h, "mm；正Y边框=", screen_window_pos_y_border,
         "mm；负Y/FPC边框=", screen_window_neg_y_border, "mm"));
echo(str("校验：裸屏凹槽=", screen_recess_w, " x ",
         screen_recess_h, " x ", screen_recess_depth,
         "mm；限位围边高=", screen_recess_guide_h,
         "mm；总有效限位深度=", screen_recess_total_limit_depth, "mm"));
echo(str("校验：FPC槽=", screen_fpc_exit_w, " x ",
         screen_fpc_exit_h, "mm；中心Y=", screen_fpc_channel_center_y,
         "mm；槽外侧剩余前框=", screen_fpc_outer_frame, "mm"));
echo(str("校验：屏幕固定=对侧盖板卡槽 + 原螺丝侧双M2；螺柱中心=±",
         screen_clamp_screw_dx/2, ", Y=", screen_clamp_screw_y,
         "mm；螺柱高=", screen_boss_h, "mm"));
echo(str("校验：屏幕异形盖板=", screen_clamp_bar_w, " x ",
         screen_clamp_bar_h, " x ", screen_clamp_bar_t,
         "mm；底面=完整平面；EVA预留间隙=", screen_cover_under_gap,
         "mm；原右侧按键缺口=",
         enable_screen_cover_button_cut ? "启用" : "关闭",
         "；FPC缺口=", screen_cover_fpc_cut_w, " x ",
         screen_cover_fpc_cut_h, "mm"));
echo(str("校验：对侧盖板卡槽X=±", screen_hook_x,
         "mm；卡钩宽=", screen_hook_w,
         "mm；扣入=", screen_hook_overhang,
         "mm；盖板插入搭接=", screen_cover_hook_engagement,
         "mm；卡槽高度间隙=", screen_hook_clearance,
         "mm；根部距LCD凹槽=", screen_hook_root_to_recess_gap,
         "mm；根部与短边内壁搭接=", screen_hook_root_wall_overlap_actual, "mm"));
echo(str("校验：FPC转接PCB=", screen_fpc_board_w, " x ",
         screen_fpc_board_h, "mm；固定孔=4 x φ",
         screen_fpc_board_hole_d, "mm"));
echo(str("校验：盖板四限位柱=X±", screen_fpc_board_post_x,
         "mm；Y=", screen_fpc_board_post_y_near, "/",
         screen_fpc_board_post_y_far,
         "mm；X向中心距=", screen_fpc_board_post_dx,
         "mm；Y向中心距=", screen_fpc_board_post_dy,
         "mm；20mm短边朝FPC；原两柱对应PCB y=8.70mm排"));
echo(str("校验：限位柱=OD", screen_fpc_board_post_d,
         " x H", screen_fpc_board_post_h,
         "mm；φ2.20孔单边理论间隙=",
         screen_fpc_board_post_radial_clearance,
         "mm；原柱列距FPC侧卡扣边缘=",
         screen_fpc_board_near_from_hook_actual, "mm"));
echo(str("校验：外壳=", body_w, " x ", body_h,
         " x ", shell_depth, "mm"));

assert(screen_recess_side_margin > 1.00,
       "错误：裸屏凹槽距离左右内壁太近");
assert(screen_recess_min_y_gap > 1.00,
       "错误：偏移后的裸屏凹槽距离某一短边内壁太近");
assert(screen_recess_guide_side_gap > 0.35,
       "错误：抬高后的屏幕限位围边距离左右内壁太近");
assert(screen_recess_guide_min_y_gap > 0.35,
       "错误：偏移后的屏幕限位围边距离某一短边内壁太近");
assert(screen_recess_guide_h <= screen_body_t - 0.20,
       "错误：屏幕限位围边过高，可能高于屏幕后表面");
assert(screen_boss_to_screen_gap > 0.10,
       "错误：保留侧螺柱底座侵入裸屏凹槽");
assert(screen_boss_to_inner_wall_gap > 0.20,
       "错误：保留侧螺柱底座距离外壳短边内壁太近");
assert(screen_clamp_bar_to_inner_wall_gap > 0.20,
       "错误：屏幕异形盖板螺丝侧顶到短边内壁");
assert(screen_cover_hook_side_wall_gap > 0.40,
       "错误：屏幕盖板卡槽侧顶到短边内壁");
assert(screen_cover_side_wall_gap > 1.50,
       "错误：屏幕盖板距离左右内壁过近");
assert(screen_cover_hook_engagement > 1.50,
       "错误：盖板插片与对侧卡槽的搭接量不足");
assert(screen_cover_fpc_to_hook_gap > 1.00,
       "错误：盖板 FPC 缺口距离卡槽插片过近");
assert(screen_hook_root_to_fpc_gap > 0.80,
       "错误：加宽后的卡槽根部距离FPC围边缺口过近");
assert(screen_hook_root_to_side_wall_gap > 1.00,
       "错误：加宽后的卡槽根部距离长边内壁过近");
assert(screen_hook_root_to_recess_gap >= 0.25,
       "错误：盖板卡钩根部仍然过于靠近或侵入LCD凹槽");
assert(screen_hook_root_wall_overlap_actual >= 0.20,
       "错误：盖板卡钩根部没有可靠搭接到短边内壁");
assert(screen_hook_base_t >= 1.40,
       "错误：盖板卡钩根部厚度不足，打印后容易断裂");
assert(!enable_screen_cover_center_relief || screen_cover_right_rail_w > 2.00,
       "错误：按键缺口与中央散热窗之间的加强条过窄");
assert(screen_fpc_board_post_side_gap > 2.00,
       "错误：FPC转接PCB限位柱距离盖板左右边缘过近");
assert(screen_fpc_board_post_d < screen_fpc_board_hole_d,
       "错误：限位柱直径必须小于PCB固定孔直径");
assert(screen_fpc_board_post_radial_clearance >= 0.10,
       "错误：FPC转接PCB限位柱与φ2.20孔的装配间隙不足");
assert(abs(screen_fpc_board_near_from_hook_actual - 23.50) < 0.01,
       "错误：对应PCB y=8.70mm的原限位柱排距卡扣边缘不是23.50mm");
assert(abs(screen_fpc_board_post_dx - 15.00) < 0.01,
       "错误：20mm短边上的两孔在盖板X方向中心距不是15.00mm");
assert(abs(screen_fpc_board_post_dy - 18.80) < 0.01,
       "错误：30mm长边上的两孔在盖板Y方向中心距不是18.80mm");
assert(screen_fpc_board_far_to_screw_end_gap > 2.00,
       "错误：新增的FPC转接PCB限位柱距离盖板螺丝侧边缘过近");
assert(screen_hook_to_fpc_gap > 1.00,
       "错误：对侧盖板卡槽距离排线缺口太近");
assert(screen_fpc_outer_frame > 1.20,
       "错误：缩短外壳后，FPC避让槽外侧剩余前框过薄");
assert(abs(screen_window_pos_y_border - screen_window_neg_y_border) < 0.02,
       "错误：前盖正面两侧边框没有等宽");
assert(abs(screen_va_to_window_y - screen_recess_shift_to_fpc) < 0.01,
       "错误：屏幕凹槽相对正面开窗的FPC侧修正量不等于1.00mm");

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

// ---------- ESP32-S3 主板：双 Type-C 口为基准定位 ----------
// 图纸：PCB=1100mil x 2250mil，ESP32模组伸出后总长约2495.63mil。
mil = 0.0254;
pico_pcb_w = 1100 * mil;              // 27.94mm，保留旧变量名以兼容原模块
pico_pcb_h = 2250 * mil;              // 57.15mm
pico_pcb_t = 1.60;                    // 图纸未标板厚，按常规1.6mm PCB设计
esp32_total_h = 2495.63 * mil;         // 63.389mm
esp32_tail_overhang_h = esp32_total_h - pico_pcb_h; // 6.239mm
esp32_module_w = 25.40;               // 图纸顶部模组宽度
esp32_module_t = 3.20;                // 仅作装配避让参考，实物可后续实测修正

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

// 两个 Type-C 均位于 -Y 短边。
pico_usb_side_y = -1;
pico_center_x = 0;

// ---------- Type-C 开孔：外壳开孔位置固定，不再由 Pico 板长反推 ----------
typec_open_w = 9.40;       // 外壳 Type-C 开孔宽；常见 USB-C 母座建议 9.2~9.8mm
typec_open_h = 3.80;       // 外壳 Type-C 开孔高；常见 USB-C 母座建议 3.6~4.0mm
typec_open_r = typec_open_h/2 - 0.05;
typec_cut_depth = wall + 5.20;

// 两个 Type-C 中心距 PCB 左右边各300mil=7.62mm，所以相对板中心为±6.35mm。
typec_open_y = pico_usb_side_y * (body_h/2 - wall/2);
typec_edge_offset = 300 * mil;         // 7.62mm
typec_open_x = pico_pcb_w/2 - typec_edge_offset; // 6.35mm，双口使用±值
typec_open_center_dx = 2 * typec_open_x; // 12.70mm

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
typec_pcb_back_gap_from_cover_inner = 1.00;  // 后盖四个边缘支撑点将PCB抬高1mm，避开背面焊点
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
enable_pico_svg_mount = false; // 旧Pico后盖固定结构停用，改用ESP32四螺柱+四小压盖

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
enable_pico_pair_clamp_covers = false;
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

// ---------- ESP32-S3 后盖固定：Type-C侧双螺柱 + 1块EVA横压板；取消PCB尾部固定螺柱 ----------
enable_esp32_mount = true;
esp32_mount_edge_clear = 0.30;
esp32_support_h = typec_pcb_back_gap_from_cover_inner; // 1.00mm
esp32_support_pad_d = 4.00;
esp32_support_pad_x = 8.50; // 向板内收，避开X=±12.70mm的两排针脚焊盘
esp32_support_pad_y_usb = pico_usb_edge_y + 7.00;
esp32_pcb_tail_y = pico_usb_edge_y + pico_pcb_h;
esp32_total_tail_y = pico_usb_edge_y + esp32_total_h;
esp32_support_pad_y_tail = esp32_pcb_tail_y - 7.00;

// 螺柱全部位于PCB左右外侧，不在板上开孔。
esp32_pin_row_end_margin = (pico_pcb_h - 2100*mil)/2; // 1.905mm
esp32_first_pin_y = pico_usb_edge_y + esp32_pin_row_end_margin;
esp32_usb_boss_x = 17.57;
esp32_mount_boss_x = esp32_usb_boss_x; // 兼容旧变量名
// Type-C侧第一对螺柱位于板边后11.00mm的空白横带，用一整条横压板。
esp32_mount_boss_y_usb = pico_usb_edge_y + 11.00;
esp32_usb_boss_y_left = esp32_mount_boss_y_usb;
// 按键位于+X长边，右侧Type-C螺柱向-Type-C端错开2.95mm，离开按键压板Y范围。
esp32_usb_boss_y_right = esp32_mount_boss_y_usb - 2.95;

// 旧版尾部第二对螺柱和两块L形压盖参数仅保留为历史兼容，不再生成或参与装配。
esp32_tail_boss_x = 19.00;
esp32_mount_boss_y_tail = esp32_pcb_tail_y + 3.40; // 26.50mm
esp32_mount_boss_od = 5.20;
esp32_mount_boss_pilot_d = 1.60;
esp32_clamp_height_gap = 0.90; // 横压板改为平底后整体下移0.30mm，保持EVA约0.10mm压缩量
esp32_mount_boss_h =
    esp32_support_h + pico_pcb_t + esp32_clamp_height_gap;

// 尾部L形小压盖：螺丝座在PCB尾端外，窄压脚回伸到PCB尾角。
esp32_edge_clamp_w = 12.00; // 打印布局参考包围尺寸
esp32_edge_clamp_h = 8.00;
esp32_edge_clamp_t = 1.60;
esp32_edge_clamp_r = 1.00;
esp32_edge_clamp_screw_d = 2.40;
esp32_edge_clamp_head_d = 4.40;
esp32_edge_clamp_head_depth = 0.75;
esp32_edge_clamp_base_d = 6.00;
esp32_edge_clamp_arm_d = 0.80;
esp32_edge_clamp_toe_w = 0.90;
esp32_edge_clamp_toe_h = 1.30;
esp32_edge_clamp_toe_len = 0.40;
esp32_edge_clamp_toe_target_x = 13.50;
esp32_edge_clamp_toe_target_y = esp32_pcb_tail_y - 0.20; // 22.90mm
esp32_edge_clamp_toe_local_x =
    esp32_tail_boss_x - esp32_edge_clamp_toe_target_x; // 5.50mm
esp32_edge_clamp_toe_local_y =
    esp32_edge_clamp_toe_target_y - esp32_mount_boss_y_tail; // -3.70mm

// Type-C后方的整条横向压板：两颗M2锁紧，中间用EVA泡棉压PCB空白区。
esp32_usb_bar_w = 2*esp32_usb_boss_x + esp32_mount_boss_od + 1.20;
esp32_usb_bar_center_w = 31.00;
esp32_usb_bar_h = 7.20;
esp32_usb_bar_t = 1.80;
esp32_usb_bar_r = 1.00;
esp32_usb_bar_screw_d = 2.40;
esp32_usb_bar_head_d = 4.40;
esp32_usb_bar_head_depth = 0.80;
esp32_usb_bar_eva_pad_w = pico_pcb_w - 2.00;
esp32_usb_bar_eva_pad_h = 3.20;
esp32_usb_bar_eva_pad_drop = 0.00; // V11：取消横压板底部轻微凸起，底面完全平整
esp32_usb_bar_eva_thickness = 1.00;
esp32_usb_bar_eva_compression =
    esp32_usb_bar_eva_pad_drop
    + esp32_usb_bar_eva_thickness
    - esp32_clamp_height_gap;
esp32_usb_bar_right_ear_local_y =
    esp32_usb_boss_y_right - esp32_mount_boss_y_usb;
esp32_typec_rear_edge_y =
    typec_shell_center_y - pico_usb_side_y*typec_shell_d/2;
esp32_usb_bar_to_typec_gap =
    (esp32_mount_boss_y_usb - esp32_usb_bar_h/2)
    - esp32_typec_rear_edge_y;

// 尾部ESP32模组只占中间25.40mm，利用左右各1.27mm PCB窄边设置止推挡块。
esp32_tail_stop_clear_y = 0.25;
esp32_tail_stop_t = 1.60;
esp32_tail_stop_w = 3.00;
esp32_tail_stop_h = esp32_support_h + pico_pcb_t + 0.80;
esp32_tail_stop_module_clear_x = 0.20;
esp32_tail_stop_inner_x = esp32_module_w/2 + esp32_tail_stop_module_clear_x;
esp32_tail_stop_x = esp32_tail_stop_inner_x + esp32_tail_stop_w/2;
esp32_tail_stop_y =
    esp32_pcb_tail_y + esp32_tail_stop_clear_y + esp32_tail_stop_t/2;
esp32_tail_stop_pcb_contact_w =
    pico_pcb_w/2 - esp32_tail_stop_inner_x;

// Type-C端只保留两个侧向导向块；尾部中间避让模组，左右两侧设止推挡块。
esp32_side_guide_w = 1.50;
esp32_side_guide_len = 8.00;
esp32_side_guide_h = esp32_support_h + pico_pcb_t + 0.60;
esp32_side_guide_x =
    pico_pcb_w/2 + esp32_mount_edge_clear + esp32_side_guide_w/2;
esp32_side_guide_y = pico_usb_edge_y + esp32_side_guide_len/2;

esp32_typec_web_w = typec_open_center_dx - typec_open_w;
esp32_tail_wall_gap = screen_inner_half_y - esp32_total_tail_y;
// 尾部螺柱与L形压盖已取消；尾部只保留无螺丝止推挡块。

echo(str("校验：ESP32-S3 PCB=", pico_pcb_w, " x ", pico_pcb_h,
         " x ", pico_pcb_t, "mm；模组尾部伸出=",
         esp32_tail_overhang_h, "mm；含伸出总长=",
         esp32_total_h, "mm"));
echo(str("校验：双Type-C中心=X±", typec_open_x,
         "mm；中心距=", typec_open_center_dx,
         "mm；两开孔中间剩余壁宽=", esp32_typec_web_w, "mm"));
echo(str("校验：ESP32 Type-C侧仅保留双螺柱=左(-", esp32_usb_boss_x,
         ",", esp32_usb_boss_y_left, ")/右(+", esp32_usb_boss_x,
         ",", esp32_usb_boss_y_right,
         ")mm；PCB尾部固定螺柱与L形压盖=已取消；尾部模组距短边内壁=",
         esp32_tail_wall_gap, "mm"));
echo(str("校验：Type-C后方EVA横压板Y=",
         esp32_mount_boss_y_usb, "mm；与Type-C本体后缘间隙=",
         esp32_usb_bar_to_typec_gap, "mm；EVA理论压缩=",
         esp32_usb_bar_eva_compression, "mm；尾部止推挡块X=±",
         esp32_tail_stop_x, "mm；接触PCB两侧窄边=",
         esp32_tail_stop_pcb_contact_w, "mm"));

assert(esp32_typec_web_w > 2.40,
       "错误：双Type-C开孔之间的中间壁过窄");
assert(esp32_tail_wall_gap > 4.00,
       "错误：ESP32模组尾部伸出后距离外壳短边内壁过近");
assert(esp32_usb_bar_eva_compression >= 0.00
       && esp32_usb_bar_eva_compression <= 0.30,
       "错误：Type-C后方横压板的EVA压缩量不合适");
assert(esp32_usb_bar_to_typec_gap >= 0.30,
       "错误：Type-C后方横压板距离接口本体过近");
assert(esp32_tail_stop_pcb_contact_w > 0.80,
       "错误：ESP32模组两侧留给尾部挡块的PCB宽度不足");
assert(esp32_tail_stop_inner_x >= esp32_module_w/2 + 0.15,
       "错误：尾部止推挡块侵入ESP32模组突出区");


// ---------- Type-C对侧短边三按键：TS-C005 4x4x4.3mm + 26x9.1mm外露焊盘PCB ----------
// 三枚开关横向排列在 +Y 短边；开关轴线沿 +Y。
// PCB平行于X-Z平面，元件面朝外壳短边，背面焊盘朝壳内。
enable_side_buttons = true;

side_button_center_x = 0.00;
side_button_pitch_x = 5.60;
side_button_center_z = 10.725; // PCB高9.10mm：上下各保留约0.525mm结构间隙

// TS-C005（用户购买规格：4x4x4.3mm；图纸H=4.3mm）。
button_switch_total_h = 4.30; // 自PCB元件面到按钮顶端的总高度
button_switch_base_h = 1.30;
button_switch_body_x = 5.20;  // 图纸主体最大外形参考
button_switch_body_z = 5.20;
button_switch_lead_span = 6.80;
// 图纸端子位置：旋转90°后中心偏移X=±1.85、Z=±2.90。
// 每个电气端子由两段重叠成T形：内段承接端子，外段向板边伸出，安装后仍可直接补焊。
button_pad_x_offset = 1.85;
button_pad_contact_z_offset = 2.90;
button_pad_contact_size_x = 0.90;
button_pad_contact_size_z = 1.00;
button_pad_toe_z_offset = 3.55;
button_pad_toe_size_x = 1.30;
button_pad_toe_size_z = 1.30;
button_mask_expansion = 0.10;
button_paste_z_offset = 2.90;
button_paste_size_x = 0.80;
button_paste_size_z = 0.90;
button_pad_exposed_out = 1.00;
button_actuator_d = 2.00;
button_actuator_h = button_switch_total_h - button_switch_base_h;
button_actuator_exposed = 0.80;

// Type-C对侧短边按键孔：φ2.60贯穿；外侧φ3.40x0.50浅凹。
button_panel_hole_d = 2.60;
button_panel_recess_d = 3.40;
button_panel_recess_depth = 0.50;

// 嘉立创PCB V6.0：26x9.1mm；正面12个按键焊盘直接在F.Cu/F.Mask中开出。
side_button_pcb_len = 26.00;        // 沿外壳X方向
side_button_pcb_h = 9.10;           // 沿外壳Z方向
side_button_pcb_t = 1.60;
side_button_pcb_r = 0.60;
side_button_pcb_screw_x = 10.50;   // 两孔中心距21.00mm
side_button_pcb_screw_hole_d = 2.20;

// 以按钮顶端外露0.80mm反推PCB位置；同时给PCB背面的M2螺丝头避让ESP32模组尾端。
side_button_outer_y = body_h/2;
side_button_inner_y = body_h/2 - wall;
side_button_pcb_component_y =
    side_button_outer_y + button_actuator_exposed - button_switch_total_h;
side_button_pcb_back_y = side_button_pcb_component_y - side_button_pcb_t;
side_button_pcb_standoff = side_button_inner_y - side_button_pcb_component_y;

// 两端M2自攻螺柱；螺丝从PCB背面沿+Y拧入。
side_button_boss_pilot_d = 1.60;
side_button_boss_body_x = 5.20;
side_button_boss_body_z = 5.20;
side_button_boss_gusset_x = 5.80;
side_button_boss_gusset_skin = 0.28;
side_button_boss_gusset_drop = 1.50; // 控制斜撑下探，保证与屏幕压板至少约1mm间隙
side_button_pilot_teardrop_top = 1.55;
side_button_pilot_mouth_relief = 0.15;

// PCB上下边缘短支撑条，避免按压时PCB弯曲。
side_button_rail_len_x = 15.00;
side_button_rail_h_z = 0.70;
side_button_rail_edge_inset = 0.10;

// 装配范围与现有屏幕/ESP32结构间隙。
side_button_pcb_x_min = -side_button_pcb_len/2;
side_button_pcb_x_max =  side_button_pcb_len/2;
side_button_pcb_y_min = side_button_pcb_back_y;
side_button_pcb_y_max = side_button_pcb_component_y;
side_button_pcb_z_min = side_button_center_z - side_button_pcb_h/2;
side_button_pcb_z_max = side_button_center_z + side_button_pcb_h/2;
side_button_to_back_cover_z_gap =
    (shell_depth - cover_t) - side_button_pcb_z_max;
side_button_to_screen_bar_z_gap =
    side_button_pcb_z_min
    - (screen_clamp_install_z + screen_clamp_bar_t);
side_button_to_esp32_tail_y_gap =
    side_button_pcb_back_y - esp32_total_tail_y;
side_button_screw_edge_margin =
    side_button_pcb_len/2 - side_button_pcb_screw_x
    - side_button_pcb_screw_hole_d/2;
side_button_actuator_top_y =
    side_button_pcb_component_y + button_switch_total_h;
side_button_body_gap =
    side_button_pitch_x - button_switch_body_x;

// 控制台校验。
echo(str("校验：Type-C对侧三按键PCB=", side_button_pcb_len, " x ",
         side_button_pcb_h, " x ", side_button_pcb_t,
         "mm；开关中心X=",
         -side_button_pitch_x, ", 0, ", side_button_pitch_x,
         "mm；中心Z=", side_button_center_z, "mm"));
echo(str("校验：TS-C005总高=", button_switch_total_h,
         "mm；按钮φ", button_actuator_d,
         "；短边通孔φ", button_panel_hole_d,
         "；外侧浅凹φ", button_panel_recess_d,
         " x ", button_panel_recess_depth,
         "mm；按钮顶端外露=",
         side_button_actuator_top_y - side_button_outer_y, "mm"));
echo(str("校验：PCB元件面Y=", side_button_pcb_component_y,
         "mm；背面Y=", side_button_pcb_back_y,
         "mm；短边内壁到PCB元件面支撑距离=",
         side_button_pcb_standoff, "mm；M2孔中心距=",
         2*side_button_pcb_screw_x, "mm"));
echo(str("校验：按键PCB占用=X", side_button_pcb_x_min,
         "~", side_button_pcb_x_max, "mm, Y",
         side_button_pcb_y_min, "~", side_button_pcb_y_max,
         "mm, Z", side_button_pcb_z_min, "~",
         side_button_pcb_z_max, "mm；后盖Z间隙=",
         side_button_to_back_cover_z_gap,
         "mm；屏幕压板Z间隙=", side_button_to_screen_bar_z_gap,
         "mm；ESP32尾端Y间隙=", side_button_to_esp32_tail_y_gap, "mm"));

assert(button_panel_hole_d > button_actuator_d + 0.30,
       "错误：φ2.60按键孔对φ2.00按钮的装配间隙不足");
assert(side_button_pcb_standoff > 1.60,
       "错误：按键PCB离+Y短边内壁过近");
assert(side_button_screw_edge_margin >= 1.20,
       "错误：紧凑按键PCB的M2孔距离板边太近");
assert(side_button_body_gap >= 0.25,
       "错误：三枚TS-C005主体横向间隙不足");
assert(abs(button_pad_contact_size_x - 0.90) < 0.001
       && abs(button_pad_contact_size_z - 1.00) < 0.001,
       "错误：T形焊盘内接触段尺寸不是0.90x1.00mm");
assert(abs(button_pad_toe_size_x - 1.30) < 0.001
       && abs(button_pad_toe_size_z - 1.30) < 0.001,
       "错误：T形焊盘外露段尺寸不是1.30x1.30mm");
assert(abs(button_pad_x_offset - 1.85) < 0.001
       && abs(button_pad_contact_z_offset - 2.90) < 0.001
       && abs(button_pad_toe_z_offset - 3.55) < 0.001,
       "错误：T形焊盘中心偏移不正确");
assert(side_button_to_back_cover_z_gap >= 0.45,
       "错误：按键PCB上边缘与后盖内表面间隙不足");
assert(side_button_to_screen_bar_z_gap >= 0.50,
       "错误：按键PCB下边缘与屏幕压板间隙不足");
assert(side_button_to_esp32_tail_y_gap >= 0.80,
       "错误：按键PCB背面与ESP32模组尾端间隙不足");

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

module at_screen_clamp_bosses() {
  // 只保留 +Y 非 FPC 侧的一排两个屏幕压条螺柱。
  for (x = [-screen_clamp_screw_dx/2,
             screen_clamp_screw_dx/2])
    translate([x, screen_clamp_screw_y, 0])
      children();
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

// ---------- ESP32-S3 后盖固定模块 ----------
module at_esp32_mount_bosses() {
  // 仅保留Type-C侧左右两颗螺柱；PCB尾部两颗固定螺柱已取消。
  translate([-esp32_usb_boss_x, esp32_usb_boss_y_left, 0])
    children();
  translate([ esp32_usb_boss_x, esp32_usb_boss_y_right, 0])
    children();
}

module esp32_board_support_pads() {
  if (enable_esp32_mount)
    for (sx = [-1, 1])
      for (y = [esp32_support_pad_y_usb, esp32_support_pad_y_tail])
        translate([sx * esp32_support_pad_x, y, cover_t - 0.02])
          cylinder(d = esp32_support_pad_d, h = esp32_support_h + 0.02);
}

module esp32_typec_side_guides() {
  if (enable_esp32_mount)
    for (sx = [-1, 1])
      add_box(
        esp32_side_guide_w,
        esp32_side_guide_len,
        esp32_side_guide_h,
        sx * esp32_side_guide_x,
        esp32_side_guide_y,
        cover_t
      );
}

module esp32_tail_stop_blocks() {
  if (enable_esp32_mount)
    for (sx = [-1, 1])
      add_box(
        esp32_tail_stop_w,
        esp32_tail_stop_t,
        esp32_tail_stop_h,
        sx * esp32_tail_stop_x,
        esp32_tail_stop_y,
        cover_t
      );
}

module esp32_mount_features() {
  if (enable_esp32_mount) {
    // 仅保留Type-C侧两颗M2螺柱，均位于PCB投影之外。
    at_esp32_mount_bosses()
      translate([0, 0, cover_t])
        cylinder(d = esp32_mount_boss_od, h = esp32_mount_boss_h);

    // 四个小支撑点只托PCB左右边缘，给背面焊点留1mm空间；支撑点不是固定螺柱。
    esp32_board_support_pads();

    // 双Type-C端仅做侧向导向，不在两个接口前方设横挡板。
    esp32_typec_side_guides();

    // 尾部中间避让ESP32模组，左右两块止推挡块承受插Type-C时的向内推力。
    esp32_tail_stop_blocks();
  }
}

module esp32_mount_boss_holes() {
  if (enable_esp32_mount)
    at_esp32_mount_bosses()
      translate([0, 0, cover_t + 0.40])
        cylinder(
          d = esp32_mount_boss_pilot_d,
          h = esp32_mount_boss_h + 0.40
        );
}

module esp32_edge_clamp_cover(side = 1) {
  // 尾部L形小压盖：side=1为右侧，side=-1为左侧镜像。
  difference() {
    union() {
      // 圆形螺丝座 + 向PCB尾角回伸的窄臂。
      hull() {
        cylinder(
          d = esp32_edge_clamp_base_d,
          h = esp32_edge_clamp_t
        );

        translate([
          -side * esp32_edge_clamp_toe_local_x,
          esp32_edge_clamp_toe_local_y,
          0
        ])
          cylinder(
            d = esp32_edge_clamp_arm_d,
            h = esp32_edge_clamp_t
          );
      }

      // 只在模组两侧的PCB尾部窄边上设置0.9 x 0.5mm压脚。
      add_box(
        esp32_edge_clamp_toe_w,
        esp32_edge_clamp_toe_len,
        esp32_edge_clamp_toe_h,
        -side * esp32_edge_clamp_toe_local_x,
        esp32_edge_clamp_toe_local_y,
        -esp32_edge_clamp_toe_h
      );
    }

    translate([0, 0, -esp32_edge_clamp_toe_h - 0.20])
      cylinder(
        d = esp32_edge_clamp_screw_d,
        h = esp32_edge_clamp_t + esp32_edge_clamp_toe_h + 0.60
      );

    translate([0, 0, esp32_edge_clamp_t - esp32_edge_clamp_head_depth])
      cylinder(
        d = esp32_edge_clamp_head_d,
        h = esp32_edge_clamp_head_depth + 0.30
      );
  }
}

module esp32_usb_clamp_bar() {
  // Type-C后方空白横带使用一整条压板，中间平台下粘1.0mm EVA泡棉。
  difference() {
    union() {
      // 中间横梁收窄到31mm，不进入+X按键压板的X占用区。
      rounded_prism(
        esp32_usb_bar_center_w,
        esp32_usb_bar_h,
        esp32_usb_bar_t,
        esp32_usb_bar_r
      );

      // 左侧螺丝耳与横梁同Y；右侧螺丝耳向-Type-C端错开，避开按键压板。
      translate([-esp32_usb_boss_x, 0, 0])
        cylinder(
          d = esp32_mount_boss_od + 1.20,
          h = esp32_usb_bar_t
        );

      translate([
        esp32_usb_boss_x,
        esp32_usb_bar_right_ear_local_y,
        0
      ])
        cylinder(
          d = esp32_mount_boss_od + 1.20,
          h = esp32_usb_bar_t
        );

      // V11：取消原0.30mm下凸EVA粘贴平台。
      // 1.0mm EVA直接粘贴在横压板完整平底面上。
    }

    translate([
      -esp32_usb_boss_x,
      0,
      -0.20
    ])
      cylinder(
        d = esp32_usb_bar_screw_d,
        h = esp32_usb_bar_t + 0.60
      );

    translate([
      esp32_usb_boss_x,
      esp32_usb_bar_right_ear_local_y,
      -0.20
    ])
      cylinder(
        d = esp32_usb_bar_screw_d,
        h = esp32_usb_bar_t + 0.60
      );

    translate([
      -esp32_usb_boss_x,
      0,
      esp32_usb_bar_t - esp32_usb_bar_head_depth
    ])
      cylinder(
        d = esp32_usb_bar_head_d,
        h = esp32_usb_bar_head_depth + 0.30
      );

    translate([
      esp32_usb_boss_x,
      esp32_usb_bar_right_ear_local_y,
      esp32_usb_bar_t - esp32_usb_bar_head_depth
    ])
        cylinder(
          d = esp32_usb_bar_head_d,
          h = esp32_usb_bar_head_depth + 0.30
        );
  }
}

module esp32_edge_clamp_covers_installed_local() {
  if (enable_esp32_mount) {
    // 仅安装Type-C侧整条EVA横压板；PCB尾部螺柱与L形小压盖已取消。
    translate([
      0,
      esp32_mount_boss_y_usb,
      cover_t + esp32_mount_boss_h
    ])
      esp32_usb_clamp_bar();
  }
}

module assembled_esp32_edge_clamp_covers() {
  translate([0, 0, shell_depth])
    rotate([0, 180, 0])
      esp32_edge_clamp_covers_installed_local();
}


// ---------- Type-C对侧三按键PCB、开孔与M2固定结构 ----------
module at_side_button_positions() {
  if (enable_side_buttons)
    for (x_offset = [-side_button_pitch_x, 0, side_button_pitch_x])
      translate([side_button_center_x + x_offset, 0,
                 side_button_center_z])
        children();
}

module at_side_button_boss_positions() {
  if (enable_side_buttons)
    for (sx = [-1, 1])
      translate([sx*side_button_pcb_screw_x, 0,
                 side_button_center_z])
        children();
}

module side_button_boss_one_supportless() {
  // 方形承压面从PCB元件面延伸到+Y短边内壁，螺丝轴线沿Y。
  half_x = side_button_boss_body_x/2;
  half_z = side_button_boss_body_z/2;

  translate([-half_x, side_button_pcb_component_y, -half_z])
    cube([
      side_button_boss_body_x,
      side_button_pcb_standoff,
      side_button_boss_body_z
    ]);

  // 正面朝下打印时增加45°斜撑，减小横向悬空。
  hull() {
    translate([
      -side_button_boss_gusset_x/2,
      side_button_inner_y - side_button_boss_gusset_skin,
      -half_z - side_button_boss_gusset_drop
    ])
      cube([
        side_button_boss_gusset_x,
        side_button_boss_gusset_skin,
        side_button_boss_gusset_skin
      ]);

    translate([
      -side_button_boss_gusset_x/2,
      side_button_pcb_component_y,
      -half_z
    ])
      cube([
        side_button_boss_gusset_x,
        side_button_boss_gusset_skin,
        side_button_boss_gusset_skin
      ]);
  }
}

module side_button_edge_support_rails() {
  if (enable_side_buttons)
    for (sz = [-1, 1]) {
      zc = side_button_center_z
           + sz*(side_button_pcb_h/2
                 - side_button_rail_h_z/2
                 - side_button_rail_edge_inset);
      translate([
        -side_button_rail_len_x/2,
        side_button_pcb_component_y,
        zc - side_button_rail_h_z/2
      ])
        cube([
          side_button_rail_len_x,
          side_button_pcb_standoff,
          side_button_rail_h_z
        ]);
    }
}

module side_button_pcb_mount_features() {
  if (enable_side_buttons) {
    at_side_button_boss_positions()
      side_button_boss_one_supportless();
    side_button_edge_support_rails();
  }
}

module side_button_teardrop_pilot_y(d, length) {
  // 水滴孔截面位于X-Z平面，沿+Y拉伸。
  r = d/2;
  rotate([-90, 0, 0])
    linear_extrude(height = length)
      union() {
        circle(d = d);
        polygon(points = [
          [-r*side_button_pilot_teardrop_top, 0],
          [-r*0.15, -r*0.78],
          [-r*0.15,  r*0.78]
        ]);
      }
}

module side_button_pcb_boss_hole_cuts() {
  pilot_len = max(0.80, side_button_pcb_standoff - 0.45);

  if (enable_side_buttons)
    at_side_button_boss_positions() {
      translate([0, side_button_pcb_component_y - 0.05, 0])
        side_button_teardrop_pilot_y(
          side_button_boss_pilot_d,
          pilot_len
        );

      translate([
        0,
        side_button_pcb_component_y
          - side_button_pilot_mouth_relief,
        0
      ])
        rotate([-90, 0, 0])
          cylinder(
            d = side_button_boss_pilot_d + 0.25,
            h = side_button_pilot_mouth_relief + 0.08
          );
    }
}

module side_button_hole_cuts() {
  if (enable_side_buttons)
    at_side_button_positions() {
      // +Y短边φ2.60贯穿孔，只露出TS-C005的φ2.00按钮凸点。
      translate([0, side_button_inner_y - 0.10, 0])
        rotate([-90, 0, 0])
          cylinder(d = button_panel_hole_d,
                   h = wall + 0.20);

      // 外侧浅凹，未按下时按钮高出整机轮廓约0.80mm。
      translate([
        0,
        side_button_outer_y - button_panel_recess_depth,
        0
      ])
        rotate([-90, 0, 0])
          cylinder(d = button_panel_recess_d,
                   h = button_panel_recess_depth + 0.10);
    }
}

module side_button_pcb_raw() {
  // 仅用于装配预览；实际PCB使用随附嘉立创Gerber V6.0下单。
  // 本地X对应外壳X，本地Y对应外壳Z，本地Z对应外壳-Y。
  difference() {
    rounded_prism(
      side_button_pcb_len,
      side_button_pcb_h,
      side_button_pcb_t,
      side_button_pcb_r
    );

    for (sx = [-side_button_pcb_screw_x,
                side_button_pcb_screw_x])
      translate([sx, 0, -0.20])
        cylinder(d = side_button_pcb_screw_hole_d,
                 h = side_button_pcb_t + 0.40);
  }
}

module side_button_pcb_installed() {
  if (enable_side_buttons)
    multmatrix([
      [1, 0,  0, side_button_center_x],
      [0, 0, -1, side_button_pcb_component_y],
      [0, 1,  0, side_button_center_z],
      [0, 0,  0, 1]
    ])
      side_button_pcb_raw();
}

module side_button_pad_references() {
  // 金色薄片按V6.0实际F.Cu显示：每个端子由接触段和外露补焊段重叠成T形。
  if (enable_side_buttons)
    at_side_button_positions()
      for (px = [-button_pad_x_offset, button_pad_x_offset])
        for (sgn = [-1, 1]) {
          color([0.90, 0.66, 0.05, 0.98])
            translate([px, side_button_pcb_component_y + 0.025,
                       sgn*button_pad_contact_z_offset])
              cube([button_pad_contact_size_x, 0.05,
                    button_pad_contact_size_z], center = true);
          color([0.90, 0.66, 0.05, 0.98])
            translate([px, side_button_pcb_component_y + 0.025,
                       sgn*button_pad_toe_z_offset])
              cube([button_pad_toe_size_x, 0.05,
                    button_pad_toe_size_z], center = true);
        }
}

module side_button_switch_references() {
  if (enable_side_buttons)
    at_side_button_positions() {
      // 5.2x5.2mm主体参考，元件面朝+Y。
      color([0.12, 0.12, 0.12, 0.72])
        translate([
          0,
          side_button_pcb_component_y + button_switch_base_h/2,
          0
        ])
          cube([
            button_switch_body_x,
            button_switch_base_h,
            button_switch_body_z
          ], center = true);

      // φ2.00按钮凸点，总高4.30mm，轴线沿+Y。
      color([0.72, 0.72, 0.72, 0.92])
        translate([
          0,
          side_button_pcb_component_y + button_switch_base_h,
          0
        ])
          rotate([-90, 0, 0])
            cylinder(d = button_actuator_d,
                     h = button_actuator_h);
    }
}

// ---------- 裸屏凹槽、加深围边、FPC侧固定钩与对侧双螺柱压条 ----------

// 围边内孔使用上下两层圆角截面做 hull：
// 底部保持原凹槽尺寸，顶部单边放宽，形成装屏导入斜面。
module screen_recess_guide_inner_cut() {
  hull() {
    translate([0, 0, -0.05])
      rounded_prism(
        screen_recess_w,
        screen_recess_h,
        0.10,
        screen_recess_r
      );

    translate([0, 0, screen_recess_guide_h - 0.05])
      rounded_prism(
        screen_recess_w + 2*screen_recess_guide_lead,
        screen_recess_h + 2*screen_recess_guide_lead,
        0.10,
        screen_recess_r + screen_recess_guide_lead
      );
  }
}

module screen_recess_guide_wall() {
  if (enable_screen_recess_guide) {
    translate([0, screen_mount_y, front_thick])
      difference() {
        rounded_prism(
          screen_recess_guide_outer_w,
          screen_recess_guide_outer_h,
          screen_recess_guide_h,
          screen_recess_r + screen_recess_guide_t
        );

        screen_recess_guide_inner_cut();

        // -Y/FPC 侧中央打开，避免围边夹住 FPC 根部和弯折区。
        translate([
          -screen_recess_guide_fpc_w/2,
          -screen_recess_guide_outer_h/2 - 0.40,
          -0.20
        ])
          cube([
            screen_recess_guide_fpc_w,
            screen_recess_guide_t + 1.80,
            screen_recess_guide_h + 0.40
          ]);
      }
  }
}

module front_screen_recess_cut() {
  rounded_cut(
    screen_recess_w,
    screen_recess_h,
    screen_recess_depth + 0.08,
    screen_recess_r,
    0,
    screen_mount_y,
    screen_front_z
  );
}

module front_screen_fpc_escape_cut() {
  // 缩短为 3.60mm 高，并向屏幕内部重叠 0.60mm，保留外侧前框强度。
  rounded_cut(
    screen_fpc_exit_w,
    screen_fpc_exit_h,
    screen_recess_depth + 0.18,
    screen_fpc_exit_r,
    0,
    screen_fpc_channel_center_y,
    screen_front_z - 0.04
  );
}

module screen_lcd_keepout_cut() {
  // V13：在所有卡钩/围边与壳体完成合并后再次清理LCD本体空间。
  // Z方向只切到屏幕后壳略上方，不会削掉位于盖板上方的扣唇。
  rounded_cut(
    screen_recess_w + 2*screen_lcd_keepout_xy_clearance,
    screen_recess_h + 2*screen_lcd_keepout_xy_clearance,
    screen_back_z - screen_front_z + screen_lcd_keepout_top_extra,
    screen_recess_r + screen_lcd_keepout_xy_clearance,
    0,
    screen_mount_y,
    screen_front_z
  );
}

module screen_mount_bosses() {
  if (enable_screen_single_side_mount) {
    at_screen_clamp_bosses() {
      translate([0, 0, screen_boss_z0])
        cylinder(d = screen_boss_base_od,
                 h = screen_boss_base_h + screen_boss_embed);

      translate([0, 0, screen_boss_z0])
        cylinder(d = screen_boss_od,
                 h = screen_boss_h);
    }
  }
}

module screen_fpc_fixed_hook_one(x) {
  // 固定钩位于 -Y/FPC 侧。V13 将竖直根部完全放到LCD凹槽之外，
  // 并让根部外侧与短边内壁搭接，避免凹槽内凸起和0.2mm级薄缝。
  // 顶部短唇仍保留原2.00mm扣入量，只位于屏幕后壳/盖板上方。
  union() {
    // 与短边内壁融合的竖直根部。
    translate([
      x - screen_hook_root_w/2,
      screen_hook_base_outer_y,
      front_thick
    ])
      cube([
        screen_hook_root_w,
        screen_hook_base_t,
        screen_hook_top_z - front_thick
      ]);

    // 顶部扣唇内侧做斜导入：顶部扣入量较小，底部达到完整扣入量。
    hull() {
      translate([
        x - screen_hook_w/2,
        screen_hook_inner_y,
        screen_hook_lip_z0
      ])
        cube([
          screen_hook_w,
          screen_hook_overhang,
          0.08
        ]);

      translate([
        x - screen_hook_w/2,
        screen_hook_inner_y,
        screen_hook_top_z - 0.08
      ])
        cube([
          screen_hook_w,
          max(0.15, screen_hook_overhang - screen_hook_lead),
          0.08
        ]);
    }
  }
}

module screen_fpc_fixed_hooks() {
  if (enable_screen_single_side_mount)
    for (x = [-screen_hook_x, screen_hook_x])
      screen_fpc_fixed_hook_one(x);
}

module screen_clamp_bar_raw() {
  // V12：异形盖板底面为完整平面，可直接贴打印平台；底部四个圆形压屏凸点已删除。
  difference() {
    union() {
      rounded_prism(
        screen_clamp_bar_w,
        screen_clamp_bar_h,
        screen_clamp_bar_t,
        screen_clamp_bar_r
      );

      // FPC 转接 PCB 的四根无孔实心限位柱，从盖板顶面向后盖方向立起。
      // 靠 FPC 的一排是原来的两柱，对应 PCB y=8.70mm；
      // 靠屏幕中心的一排为新增两柱，对应 PCB y=27.50mm。
      for (x = [-screen_fpc_board_post_x, screen_fpc_board_post_x])
        for (y = [screen_fpc_board_post_y_near,
                  screen_fpc_board_post_y_far])
          translate([
            x,
            y - screen_clamp_bar_center_y,
            screen_clamp_bar_t - 0.02
          ])
            cylinder(
              d = screen_fpc_board_post_d,
              h = screen_fpc_board_post_h + 0.02
            );
    }

    // -Y/FPC 端中央开口：排线可直接向后盖方向折出。
    translate([
      0,
      -screen_clamp_bar_h/2 + screen_cover_fpc_cut_h/2 - 0.10,
      screen_clamp_bar_t/2
    ])
      cube([
        screen_cover_fpc_cut_w,
        screen_cover_fpc_cut_h,
        screen_clamp_bar_t + screen_clamp_pad_h + 0.60
      ], center = true);

    // V6：按键已移动到+Y短边，默认关闭原+X右侧避让缺口。
    if (enable_screen_cover_button_cut)
      translate([
        screen_clamp_bar_w/2 - screen_cover_button_cut_w/2 + 0.10,
        screen_cover_button_cut_y - screen_clamp_bar_center_y,
        screen_clamp_bar_t/2
      ])
        cube([
          screen_cover_button_cut_w,
          screen_cover_button_cut_h,
          screen_clamp_bar_t + screen_clamp_pad_h + 0.60
        ], center = true);

    // 中央减重/散热窗：保留四周框架刚度，也避免盖板大面积压住屏幕后壳。
    if (enable_screen_cover_center_relief)
      rounded_cut(
        screen_cover_center_relief_w,
        screen_cover_center_relief_h,
        screen_clamp_bar_t + 0.40,
        screen_cover_center_relief_r,
        0,
        screen_mount_y - screen_clamp_bar_center_y,
        -0.20
      );

    // 两个 M2 通孔，孔位靠压板外侧。
    for (x = [-screen_clamp_screw_dx/2,
               screen_clamp_screw_dx/2])
      translate([
        x,
        screen_clamp_screw_local_y,
        -screen_clamp_pad_h - 0.20
      ])
        cylinder(
          d = screen_clamp_screw_clear_d,
          h = screen_clamp_bar_t + screen_clamp_pad_h + 0.50
        );

    // 螺丝头浅沉孔。
    for (x = [-screen_clamp_screw_dx/2,
               screen_clamp_screw_dx/2])
      translate([
        x,
        screen_clamp_screw_local_y,
        screen_clamp_bar_t - screen_clamp_head_depth
      ])
        cylinder(
          d = screen_clamp_head_d,
          h = screen_clamp_head_depth + 0.30
        );
  }
}

module screen_clamp_bar_installed() {
  if (enable_screen_single_side_mount)
    translate([
      0,
      screen_clamp_bar_center_y,
      screen_clamp_install_z
    ])
      screen_clamp_bar_raw();
}

module rear_rabbet_cut() {
  // 后口削薄形成台阶，后盖落入这里再点胶。
  translate([0, 0, shell_depth - rear_rebate_depth])
    rounded_prism(rear_rebate_w, rear_rebate_h,
                  rear_rebate_depth + 0.80,
                  max(0.10, corner_r - rear_edge_wall));
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

        // 裸屏主体浅凹槽和 FPC 下边避让。
        front_screen_recess_cut();
        front_screen_fpc_escape_cut();
      }

      // 裸屏凹槽四周向后抬高的限位围边；-Y 侧保留 FPC 缺口。
      screen_recess_guide_wall();

      // -Y/FPC 侧两个固定插入卡钩。
      screen_fpc_fixed_hooks();

      // +Y 非 FPC 侧保留的一排两个 M2 压条螺柱。
      screen_mount_bosses();

      // Type-C对侧三按键PCB的两颗M2螺柱和上下防弯支撑条。
      side_button_pcb_mount_features();
    }

    // ESP32-S3 双 Type-C 短边开孔，中心位于X=±6.35mm。
    for (x = [-typec_open_x, typec_open_x])
      side_typec_cut(typec_open_w, typec_open_h,
                     typec_cut_depth, typec_open_r,
                     x, typec_open_y,
                     typec_open_center_z);

    // Type-C对侧短边三个φ2.60按键孔和外侧浅凹。
    side_button_hole_cuts();

    // Type-C对侧按键PCB固定螺柱M2自攻盲孔。
    side_button_pcb_boss_hole_cuts();

    // 后盖凸点对应的前壳浅凹窝。
    front_shell_arc_scoop_cuts();

    // V13：最后再次清理LCD凹槽本体空间，确保卡钩根部或布尔融合不会侵入。
    screen_lcd_keepout_cut();

    // +Y 侧两个屏幕压条螺柱的 M2 自攻底孔。
    // 孔底从 Z=front_thick 开始，不切穿前面板外表面。
    if (enable_screen_single_side_mount)
      at_screen_clamp_bosses()
        translate([0, 0, front_thick])
          cylinder(
            d = screen_boss_pilot_d,
            h = screen_clamp_install_z
                - front_thick + 0.30
          );
  }
}

// ---------- 后盖 ----------
module back_cover() {
  // 后盖仅保留ESP32-S3 Type-C侧双螺柱、四个边缘支撑点、Type-C侧导向块和四周弧形凸点。
  // PCB尾部固定螺柱与L形小压盖已取消；尾部只在ESP32模组两侧保留无螺丝止推挡块。
  // 三枚按键使用前壳右侧的独立贴片PCB，不在后盖增加按键结构。
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
      esp32_mount_features();
    }

    // Type-C侧两颗ESP32横压板螺柱的M2自攻底孔。
    esp32_mount_boss_holes();
  }
}

// ---------- 同平面打印布局 ----------
module print_plate() {
  // 左侧：前壳屏幕面朝下。
  translate([-(body_w/2 + plate_gap/2), 0, 0])
    front_shell();

  // 中间右侧：后盖外侧朝下。
  translate([(cover_w/2 + plate_gap/2), 0, 0])
    back_cover();

  // V12：屏幕盖板底面完整平整，Z=0直接贴平台打印。
  translate([
    cover_w + plate_gap
      + screen_clamp_bar_print_w/2,
    0,
    0
  ])
    screen_clamp_bar_raw();

  // Type-C后方的整条EVA横压板；V11底面已改为完整平面，直接贴平台打印。
  translate([
    (cover_w/2 + plate_gap/2),
    -(cover_h/2
      + esp32_usb_bar_h/2
      + plate_gap/2),
    0
  ])
    esp32_usb_clamp_bar();

  // 三按键改用独立PCB，print_plate中不再生成塑料按键压板。
}

// ---------- 预览参考 ----------
module screen_reference() {
  // 42.72 x 58.80 x 2.20mm 裸屏主体，当前向 FPC 侧总偏移 2.92mm。
  color([0.12, 0.18, 0.22, 0.38])
    translate([
      0,
      screen_mount_y,
      screen_front_z + screen_body_t/2
    ])
      cube(
        [screen_body_w, screen_body_h, screen_body_t],
        center = true
      );

  // VA 有效显示区相对原开窗向 FPC 侧偏移 1.00mm，用于修正实物约 2mm 的黑边差。
  color([0.0, 0.0, 0.0, 0.58])
    translate([
      0,
      screen_mount_y + screen_aa_y_offset,
      screen_front_z - 0.04
    ])
      cube(
        [screen_aa_w, screen_aa_h, 0.12],
        center = true
      );

  // FPC 根部直出参考，随后向后盖方向折弯。
  color([0.95, 0.55, 0.08, 0.62])
    translate([
      0,
      screen_mount_y - screen_body_h/2 - 2.20,
      screen_back_z - screen_fpc_t/2
    ])
      cube(
        [screen_fpc_root_w, 4.40, screen_fpc_t],
        center = true
      );

  // FPC 折向后盖的尾部参考，不参与实体布尔运算。
  color([0.95, 0.55, 0.08, 0.52])
    translate([
      0,
      screen_mount_y - screen_body_h/2 - 4.20,
      screen_back_z + 4.00
    ])
      cube(
        [screen_fpc_tail_w, screen_fpc_t, 8.00],
        center = true
      );
}

module pico_reference() {
  // ESP32-S3 PCB 外形参考。
  color([0.05, 0.20, 0.90, 0.28])
    translate([pico_center_x, pico_center_y, pico_board_center_z])
      cube([pico_pcb_w, pico_pcb_h, pico_pcb_t], center = true);

  // 尾部ESP32模组伸出PCB的6.239mm参考区，后盖此处不放挡板。
  color([0.60, 0.15, 0.80, 0.46])
    translate([
      pico_center_x,
      esp32_pcb_tail_y + esp32_tail_overhang_h/2,
      pico_board_front_z - esp32_module_t/2
    ])
      cube(
        [esp32_module_w, esp32_tail_overhang_h, esp32_module_t],
        center = true
      );

  // 两个Type-C连接器本体与口面参考。
  for (x = [-typec_open_x, typec_open_x]) {
    color([1.0, 0.45, 0.10, 0.55])
      translate([x, typec_shell_center_y, typec_open_center_z])
        cube([typec_shell_w, typec_shell_d, typec_shell_h], center = true);

    color([1.0, 0.10, 0.10, 0.70])
      translate([x, typec_connector_mouth_y, typec_open_center_z])
        cube([typec_open_w, 0.40, typec_open_h], center = true);
  }
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
} else if (part == "screen_clamp_bar"
           || part == "screen_x_backplate") {
  // V12：屏幕盖板平底，Z=0直接导出。
  screen_clamp_bar_raw();
} else if (part == "back_cover") {
  back_cover();
} else if (part == "esp32_usb_clamp_bar") {
  // V11：横压板平底，Z=0直接导出。
  esp32_usb_clamp_bar();
 } else if (part == "side_button_pcb_reference"
           || part == "side_button_plate"
           || part == "button_plate") {
  // 兼容旧part名称：仅显示PCB参考实体，不是需要打印的塑料件。
  color([0.05, 0.45, 0.12, 0.90])
    side_button_pcb_raw();
} else if (part == "typec_clamp_cover") {
  typec_clamp_cover();
} else if (part == "typec_fit_test") {
  typec_fit_test();
} else if (part == "exploded") {
  translate([0, 0, 0])
    front_shell();

  translate([0, 0, 28])
    back_cover();

  // 三按键PCB从+Y短边向壳内侧（-Y）分离，方便检查安装关系。
  color([0.05, 0.45, 0.12, 0.90])
    translate([0, -8, 0])
      side_button_pcb_installed();
  translate([0, -8, 0])
    side_button_pad_references();
  translate([0, -8, 0])
    side_button_switch_references();

  screen_reference();

  // 屏幕直条压板沿 Z 方向向后分离，便于检查双螺柱和两个压点。
  translate([0, 0, 10])
    screen_clamp_bar_installed();

  // ESP32 Type-C侧EVA横压板随后盖向后分离；尾部小压盖已取消。
  translate([0, 0, 28])
    esp32_edge_clamp_covers_installed_local();
} else {
  color([0.86, 0.86, 0.86, 1.0])
    front_shell();

  color([0.70, 0.70, 0.70, 0.85])
    assembled_back_cover();

  color([0.55, 0.55, 0.55, 0.85])
    assembled_esp32_edge_clamp_covers();

  color([0.05, 0.45, 0.12, 0.90])
    side_button_pcb_installed();
  side_button_pad_references();

  side_button_switch_references();
  screen_reference();

  color([0.42, 0.42, 0.42, 0.92])
    screen_clamp_bar_installed();

  pico_reference();

  // 双 Type-C 开孔参考。
  color([1.0, 0.20, 0.10, 0.45])
    for (x = [-typec_open_x, typec_open_x])
      side_typec_cut(typec_open_w, typec_open_h,
                     1.80, typec_open_r,
                     x, typec_open_y,
                     typec_open_center_z);
}
