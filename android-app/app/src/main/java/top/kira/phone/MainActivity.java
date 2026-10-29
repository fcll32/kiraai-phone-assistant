package top.kira.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.util.Locale;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int BG = 0xfffffbfe, INK = 0xff292527, MUTED = 0xff796e74;
    private static final int PINK = 0xffffdce3, SOFT = 0xfffff0f3, ACCENT = 0xff8b4d60, LINE = 0xffe7dde1;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final String[] titles = {"设备连接", "连接设置", "使用说明", "关于"};
    private final ScrollView[] pages = new ScrollView[4];
    private final LinearLayout[] navigation = new LinearLayout[4];
    private FrameLayout root, pageHost;
    private LinearLayout mainContent, drawer;
    private View scrim;
    private TextView title, connectionTitle, connectionDetail, serverLabel, accessLabel, drawerStatus;
    private Button connectionButton;
    private EditText url, token, pin;
    private int currentPage = -1;
    private boolean drawerOpen;
    private final Runnable refresh = new Runnable() {
        @Override public void run() { updateStatus(); handler.postDelayed(this, 1000); }
    };

    private SharedPreferences prefs() { return getSharedPreferences("connection", MODE_PRIVATE); }
    private int dp(float n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private LinearLayout column() {
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout;
    }
    private GradientDrawable shape(int color, int radius) {
        GradientDrawable background = new GradientDrawable();
        background.setColor(color); background.setCornerRadius(dp(radius)); return background;
    }
    private void touchBackground(View view, int color, int radius) {
        view.setBackground(new RippleDrawable(ColorStateList.valueOf(0x228b4d60), shape(color, radius), shape(Color.WHITE, radius)));
    }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        view.setFontFeatureSettings("kern"); view.setLineSpacing(dp(3), 1); return view;
    }
    private void gap(LinearLayout parent, int height) { parent.addView(new View(this), new LinearLayout.LayoutParams(1, dp(height))); }
    private void divider(LinearLayout parent) {
        View line = new View(this); line.setBackgroundColor(LINE);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(1)); params.setMargins(0, dp(14), 0, dp(14));
        parent.addView(line, params);
    }
    private void heading(LinearLayout parent, String value) {
        TextView label = text(value, 14, ACCENT); label.setPadding(0, dp(18), 0, dp(14)); parent.addView(label);
    }
    private Button button(LinearLayout parent, String label, boolean primary, Runnable action) {
        Button button = new Button(this); button.setAllCaps(false); button.setText(label); button.setTextSize(16);
        button.setTextColor(primary ? ACCENT : INK); button.setElevation(0); button.setStateListAnimator(null);
        button.setMinHeight(dp(52)); button.setMinimumHeight(dp(52)); button.setPadding(dp(16), dp(12), dp(16), dp(12));
        touchBackground(button, primary ? PINK : SOFT, 26);
        button.setOnClickListener(v -> action.run());
        parent.addView(button, new LinearLayout.LayoutParams(-1, -2)); return button;
    }
    private LinearLayout row(LinearLayout parent, int icon, String label, String detail, Runnable action) {
        LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL); row.setMinimumHeight(dp(76));
        row.setPadding(dp(4), dp(16), dp(4), dp(16));
        row.addView(new LineIcon(icon), new LinearLayout.LayoutParams(dp(26), dp(26)));
        LinearLayout words = column(); LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -2, 1); params.setMargins(dp(20), 0, dp(8), 0);
        row.addView(words, params); words.addView(text(label, 17, INK));
        if (detail != null) { TextView sub = text(detail, 13, MUTED); sub.setPadding(0, dp(5), 0, 0); words.addView(sub); }
        if (action != null) {
            row.addView(new LineIcon(7), new LinearLayout.LayoutParams(dp(18), dp(18)));
            touchBackground(row, Color.TRANSPARENT, 14); row.setOnClickListener(v -> action.run()); row.setFocusable(true);
        }
        parent.addView(row, new LinearLayout.LayoutParams(-1, -2)); return words;
    }
    private EditText field(LinearLayout parent, String label, String value, String hint, boolean secret) {
        parent.addView(text(label, 14, MUTED)); gap(parent, 8);
        EditText field = new EditText(this); field.setTextSize(15); field.setTextColor(INK); field.setHintTextColor(MUTED);
        field.setSingleLine(true); field.setInputType(InputType.TYPE_CLASS_TEXT |
            (secret ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_VARIATION_URI));
        field.setText(value); field.setHint(hint); field.setContentDescription(label);
        field.setPadding(dp(16), dp(14), dp(16), dp(14)); field.setMinimumHeight(dp(54));
        GradientDrawable background = shape(0xfffaf4f7, 14); background.setStroke(dp(1), LINE); field.setBackground(background);
        field.setBackgroundTintList(null); field.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        parent.addView(field, new LinearLayout.LayoutParams(-1, -2)); gap(parent, 22); return field;
    }
    private LinearLayout page(int index) {
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setClipToPadding(false);
        scroll.setVerticalScrollBarEnabled(false); LinearLayout body = column();
        body.setPadding(dp(24), dp(12), dp(24), dp(32)); scroll.addView(body);
        pages[index] = scroll; pageHost.addView(scroll, new FrameLayout.LayoutParams(-1, -1)); scroll.setVisibility(View.GONE); return body;
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        getWindow().setStatusBarColor(BG); getWindow().setNavigationBarColor(BG);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if (!prefs().contains("device_id")) prefs().edit().putString("device_id", UUID.randomUUID().toString()).apply();
        root = new FrameLayout(this); root.setBackgroundColor(BG); setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                int bottom = Build.VERSION.SDK_INT >= 35 ? Math.max(bars.bottom, insets.getInsets(WindowInsets.Type.ime()).bottom) : bars.bottom;
                view.setPadding(bars.left, bars.top, bars.right, bottom);
            } else view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        root.requestApplyInsets(); mainContent = column(); root.addView(mainContent, new FrameLayout.LayoutParams(-1, -1));
        LinearLayout toolbar = new LinearLayout(this); toolbar.setGravity(Gravity.CENTER_VERTICAL); toolbar.setPadding(dp(8), dp(4), dp(20), dp(4));
        LineIcon menu = new LineIcon(0); menu.setContentDescription("打开导航菜单"); menu.setFocusable(true);
        menu.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        touchBackground(menu, Color.TRANSPARENT, 24); menu.setOnClickListener(v -> setDrawer(true));
        toolbar.addView(menu, new LinearLayout.LayoutParams(dp(48), dp(48)));
        title = text("", 22, INK); title.setPadding(dp(12), 0, 0, 0); toolbar.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        mainContent.addView(toolbar, new LinearLayout.LayoutParams(-1, -2));
        pageHost = new FrameLayout(this); mainContent.addView(pageHost, new LinearLayout.LayoutParams(-1, 0, 1));
        buildHome(); buildSettings(); buildHelp(); buildAbout(); buildDrawer();
        showPage(saved == null ? 0 : Math.max(0, Math.min(3, saved.getInt("page", 0))), false);
        updateStatus();
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
    }
    private void buildHome() {
        LinearLayout body = page(0); gap(body, 14);
        TextView lead = text(getString(R.string.app_name), 25, INK); lead.setTypeface(null, Typeface.BOLD); body.addView(lead);
        gap(body, 8); body.addView(text("连接你的服务器，按需操作与截图。", 14, MUTED)); gap(body, 28);
        LinearLayout card = column(); card.setPadding(dp(22), dp(24), dp(22), dp(22)); card.setBackground(shape(SOFT, 24));
        TextView mark = text("AI", 22, ACCENT); mark.setGravity(Gravity.CENTER); mark.setTypeface(null, Typeface.BOLD); mark.setBackground(shape(PINK, 28));
        card.addView(mark, new LinearLayout.LayoutParams(dp(52), dp(52))); gap(card, 20);
        connectionTitle = text("未连接", 23, INK); card.addView(connectionTitle); gap(card, 6);
        connectionDetail = text("", 14, MUTED); card.addView(connectionDetail); gap(card, 24);
        connectionButton = button(card, "开始连接", true, () -> {
            if (ConnectionService.running) { stopService(new Intent(this, ConnectionService.class)); ConnectionService.status = "已停止"; handler.postDelayed(this::updateStatus, 100); }
            else begin();
        }); body.addView(card, new LinearLayout.LayoutParams(-1, -2)); gap(body, 20);
        LinearLayout server = row(body, 2, "连接设置", "", () -> showPage(1, true)); serverLabel = (TextView)server.getChildAt(1);
        LinearLayout access = row(body, 3, "无障碍服务", "", this::openAccessibility); accessLabel = (TextView)access.getChildAt(1);
        divider(body); body.addView(text(Build.VERSION.SDK_INT >= 30 ? "按需单张截图 · 不录屏 · 随时停止" : "当前系统提供界面信息与控制，不采集截图。", 13, MUTED));
    }
    private void buildSettings() {
        LinearLayout body = page(1); body.addView(text("地址只填公网 IP 和端口，后面的内容会自动补上。", 14, MUTED)); gap(body, 26);
        url = field(body, "服务器地址", ServerAddress.display(prefs().getString("url", "")), "例如 203.0.113.10:5267", false);
        token = field(body, "连接密码", prefs().getString("token", ""), "复制插件页面显示的密码", true);
        pin = field(body, "服务器校验码", prefs().getString("pin", ""), "复制插件页面显示的校验码", false);
        url.setId(101); token.setId(102); pin.setId(103);
        body.addView(text("校验码用来确认连的是你的服务器。按新手说明搭建时直接复制；已有可信证书时可以留空。", 13, MUTED)); gap(body, 28);
        button(body, "保存设置", true, () -> {
            try { String[] config = readConfig(); saveConfig(config); hideKeyboard(); showPage(0, true); toast("连接设置已保存"); }
            catch (Exception error) { toast(error.getMessage()); }
        }); gap(body, 12); body.addView(text("修改配置前，请先停止连接。", 13, MUTED));
        heading(body, "设备"); row(body, 6, "复制设备 ID", "用于插件中绑定这台手机", () -> {
            ClipboardManager clipboard = (ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
            clipboard.setPrimaryClip(ClipData.newPlainText("Kira device ID", prefs().getString("device_id", ""))); toast("设备 ID 已复制");
        });
    }
    private void buildHelp() {
        LinearLayout body = page(2); heading(body, "开始使用");
        row(body, 2, "1. 填写连接信息", "打开 KiraAI 的手机连接页，复制地址、连接密码和服务器校验码。", () -> showPage(1, true));
        row(body, 3, "2. 开启无障碍", "允许 Kira 查看界面、点击、滑动和输入。", this::openAccessibility);
        row(body, 1, "3. 开始连接", "回到设备连接页，连接后即可在 KiraAI 中下达任务。", () -> showPage(0, true));
        divider(body); heading(body, "截图与控制");
        body.addView(text("Android 11 及以上按需发送单张截图。Android 8–10 仅提供界面文字和控件位置。\n\n不录屏、不录音。AI 可按需发送文字进度。你可以随时通过 App 或通知停止控制。", 15, MUTED));
        heading(body, "连接遇到问题？");
        body.addView(text("先检查 IP、端口、连接密码和服务器校验码有没有复制错。首次安装若无障碍选项受限，请在系统应用信息中允许受限设置。\n\n后台连接被中断时，可在系统设置中允许 App 后台运行。", 15, MUTED));
    }
    private void buildAbout() {
        LinearLayout body = page(3); gap(body, 20);
        LinearLayout identity = new LinearLayout(this); identity.setGravity(Gravity.CENTER_VERTICAL);
        TextView avatar = text("AI", 26, ACCENT); avatar.setTypeface(null, Typeface.BOLD); avatar.setGravity(Gravity.CENTER); avatar.setBackground(shape(PINK, 32));
        identity.addView(avatar, new LinearLayout.LayoutParams(dp(64), dp(64)));
        LinearLayout name = column(); LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-2, -2); params.setMargins(dp(20), 0, 0, 0); identity.addView(name, params);
        name.addView(text(getString(R.string.app_name), 20, INK)); gap(name, 4); name.addView(text("版本 " + version(), 14, MUTED)); body.addView(identity); gap(body, 24);
        row(body, 1, "手机主动连接", "支持公网服务器，无需手机端内网穿透。", null);
        row(body, 3, "由你掌控", "手动开始，随时停止。连接密码保存在这个 App 内。", null);
        row(body, 4, "开源组件", "Java-WebSocket · SLF4J", this::showLicenses);
        divider(body); body.addView(text("为 KiraAI 提供手机控制能力。\n轻量连接，按需观察。", 14, MUTED));
    }
    private void buildDrawer() {
        scrim = new View(this); scrim.setBackgroundColor(0x55000000); scrim.setVisibility(View.GONE); scrim.setOnClickListener(v -> setDrawer(false));
        root.addView(scrim, new FrameLayout.LayoutParams(-1, -1));
        drawer = column(); drawer.setClickable(true); drawer.setBackground(shape(BG, 24)); drawer.setElevation(dp(12)); drawer.setPadding(dp(16), dp(28), dp(16), dp(20));
        int width = Math.min(dp(312), getResources().getDisplayMetrics().widthPixels - dp(40));
        FrameLayout.LayoutParams bounds = new FrameLayout.LayoutParams(width, -1, Gravity.START); root.addView(drawer, bounds); drawer.setVisibility(View.GONE);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setVerticalScrollBarEnabled(false); drawer.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        LinearLayout entries = column(); scroll.addView(entries);
        TextView brand = text(getString(R.string.app_name), 24, INK); brand.setPadding(dp(16), dp(12), 0, dp(8)); brand.setTypeface(null, Typeface.BOLD); entries.addView(brand);
        drawerStatus = text("", 14, MUTED); drawerStatus.setPadding(dp(16), 0, 0, dp(16)); entries.addView(drawerStatus); divider(entries);
        String[] labels = {"设备连接", "连接设置", "使用说明", "关于"};
        for (int i = 0; i < labels.length; i++) {
            if (i == 3) divider(entries);
            final int index = i;
            LinearLayout item = new LinearLayout(this); item.setPadding(dp(16), dp(18), dp(12), dp(18)); item.setGravity(Gravity.CENTER_VERTICAL); item.setMinimumHeight(dp(60));
            item.addView(new LineIcon(i + 1), new LinearLayout.LayoutParams(dp(25), dp(25)));
            TextView label = text(labels[i], 17, INK); LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -2, 1); params.setMargins(dp(20), 0, 0, 0); item.addView(label, params);
            item.setOnClickListener(v -> { showPage(index, true); setDrawer(false); }); item.setFocusable(true); navigation[i] = item;
            entries.addView(item, new LinearLayout.LayoutParams(-1, -2)); gap(entries, 4);
        }
        gap(entries, 24); TextView footer = text("KiraAI Phone Assistant  " + version(), 12, MUTED); footer.setPadding(dp(16), 0, 0, 0); entries.addView(footer);
    }
    private void setDrawer(boolean open) {
        hideKeyboard(); drawerOpen = open; drawer.animate().cancel(); scrim.animate().cancel();
        if (open) {
            mainContent.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
            if (drawer.getVisibility() != View.VISIBLE) { drawer.setTranslationX(-drawer.getLayoutParams().width); scrim.setAlpha(0); }
            drawer.setVisibility(View.VISIBLE); scrim.setVisibility(View.VISIBLE);
            drawer.animate().translationX(0).setDuration(220).start(); scrim.animate().alpha(1).setDuration(180).start();
            navigation[currentPage].requestFocus();
        } else {
            mainContent.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
            drawer.animate().translationX(-drawer.getWidth()).setDuration(200).withEndAction(() -> { if (!drawerOpen) drawer.setVisibility(View.GONE); }).start();
            scrim.animate().alpha(0).setDuration(180).withEndAction(() -> { if (!drawerOpen) scrim.setVisibility(View.GONE); }).start();
        }
    }
    private void showPage(int index, boolean animate) {
        hideKeyboard(); if (currentPage == index) return;
        for (ScrollView page : pages) { page.animate().cancel(); page.setVisibility(View.GONE); }
        currentPage = index; title.setText(titles[index]); ScrollView selected = pages[index]; selected.setVisibility(View.VISIBLE);
        selected.setAlpha(animate ? 0 : 1); selected.setTranslationY(animate ? dp(8) : 0);
        if (animate) selected.animate().alpha(1).translationY(0).setDuration(160).start();
        for (int i = 0; i < navigation.length; i++) if (navigation[i] != null) {
            navigation[i].setSelected(i == index); touchBackground(navigation[i], i == index ? PINK : Color.TRANSPARENT, 28);
        }
        updateStatus();
    }
    private void updateStatus() {
        if (connectionTitle == null) return;
        String state = ConnectionService.status;
        setText(connectionTitle, ConnectionService.running ? (state.startsWith("已连接") ? "已连接" : "连接中") : "未连接");
        setText(connectionDetail, ConnectionService.running || !state.equals("已停止") ? state : "准备好后，开始连接你的服务器。");
        setText(connectionButton, ConnectionService.running ? "停止连接" : "开始连接");
        String host = "尚未配置，点击填写";
        try { String saved = prefs().getString("url", ""); if (!saved.isEmpty()) host = ServerAddress.display(saved); } catch (Exception ignored) { }
        setText(serverLabel, host == null ? "请检查服务器地址" : host);
        setText(accessLabel, PhoneAccessibility.instance == null ? "未开启，点击前往系统设置" : "已开启");
        if (drawerStatus != null) setText(drawerStatus, ConnectionService.running || !state.equals("已停止") ? state : "你的手机，由你掌控");
    }
    private void setText(TextView view, String value) { if (!value.contentEquals(view.getText())) view.setText(value); }
    private String[] readConfig() {
        if (ConnectionService.running) throw new IllegalArgumentException("请先停止连接，再修改服务器配置");
        String address = ServerAddress.normalize(url.getText().toString());
        String secret = token.getText().toString(); if (!ConnectionPassword.valid(secret)) throw new IllegalArgumentException("连接密码需 8–128 位英文字母、数字或符号，不含空格");
        String fingerprint = pin.getText().toString().replaceAll("[\\s:]", "").toLowerCase(Locale.ROOT);
        if (!fingerprint.isEmpty() && !fingerprint.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("校验码不完整，应是服务器给出的 64 位字母和数字");
        return new String[]{address, secret, fingerprint};
    }
    private void saveConfig(String[] config) {
        prefs().edit().putString("url", config[0]).putString("token", config[1]).putString("pin", config[2]).apply();
        url.setText(ServerAddress.display(config[0]));
    }
    private void begin() {
        final String[] config;
        try { config = readConfig(); }
        catch (Exception error) { showPage(1, true); toast(error.getMessage()); return; }
        if (PhoneAccessibility.instance == null) {
            new AlertDialog.Builder(this).setTitle("先开启无障碍服务").setMessage("开启后，Kira 才能查看界面并操作手机。")
                .setNegativeButton("稍后", null).setPositiveButton("前往设置", (dialog, which) -> openAccessibility()).show(); return;
        }
        new AlertDialog.Builder(this).setTitle("允许此服务器控制手机？")
            .setMessage(ServerAddress.display(config[0]) + "\n\n连接期间可查看屏幕、点击、滑动和输入。你可以随时停止。")
            .setNegativeButton("取消", null).setPositiveButton("开始连接", (dialog, which) -> {
                saveConfig(config); startForegroundService(new Intent(this, ConnectionService.class)); handler.postDelayed(this::updateStatus, 100);
            }).show();
    }
    private void openAccessibility() { startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)); }
    private void hideKeyboard() {
        View focused = getCurrentFocus();
        if (focused != null) ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(focused.getWindowToken(), 0);
    }
    private void toast(String value) { Toast.makeText(this, value, Toast.LENGTH_LONG).show(); }
    private String version() {
        try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionName; } catch (Exception error) { return "未知"; }
    }
    private void showLicenses() {
        try {
            StringBuilder licenses = new StringBuilder();
            for (String file : new String[]{"Java-WebSocket-LICENSE.txt", "SLF4J-LICENSE.txt"}) {
                licenses.append(file).append("\n\n");
                try (java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(getAssets().open("licenses/" + file), java.nio.charset.StandardCharsets.UTF_8))) {
                    String line; while ((line = reader.readLine()) != null) licenses.append(line).append('\n');
                } licenses.append("\n\n");
            }
            ScrollView scroll = new ScrollView(this); TextView content = text(licenses.toString(), 13, MUTED); content.setPadding(dp(24), dp(12), dp(24), dp(24)); scroll.addView(content);
            new AlertDialog.Builder(this).setTitle("开源许可").setView(scroll).setPositiveButton("关闭", null).show();
        } catch (Exception error) { toast("暂时无法读取开源许可"); }
    }
    @Override public void onBackPressed() {
        if (drawerOpen) setDrawer(false); else if (currentPage != 0) showPage(0, true); else super.onBackPressed();
    }
    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); state.putInt("page", currentPage); }
    @Override protected void onResume() { super.onResume(); handler.removeCallbacks(refresh); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacksAndMessages(null); super.onPause(); }

    private class LineIcon extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int kind;
        LineIcon(int kind) { super(MainActivity.this); this.kind = kind; setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO); }
        @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
            super.onInitializeAccessibilityNodeInfo(info); if (isClickable()) info.setClassName("android.widget.Button");
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); canvas.save(); float size = Math.min(getWidth(), getHeight());
            if (kind == 0) size = dp(24);
            canvas.translate((getWidth() - size) / 2, (getHeight() - size) / 2); canvas.scale(size / 24, size / 24);
            paint.setColor(0xff5d5359); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(1.9f); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND);
            if (kind == 0) { canvas.drawLine(4,6,20,6,paint); canvas.drawLine(4,12,20,12,paint); canvas.drawLine(4,18,16,18,paint); }
            else if (kind == 1) { canvas.drawRoundRect(6,2,18,22,3,3,paint); canvas.drawLine(10,18,14,18,paint); }
            else if (kind == 2) {
                canvas.drawLine(3,6,21,6,paint); canvas.drawLine(3,12,21,12,paint); canvas.drawLine(3,18,21,18,paint);
                paint.setStyle(Paint.Style.FILL); canvas.drawCircle(8,6,3,paint); canvas.drawCircle(16,12,3,paint); canvas.drawCircle(9,18,3,paint);
            } else if (kind == 3) {
                android.graphics.Path path = new android.graphics.Path(); path.moveTo(12,2); path.lineTo(20,6); path.lineTo(19,14); path.quadTo(17,20,12,22); path.quadTo(7,20,5,14); path.lineTo(4,6); path.close(); canvas.drawPath(path,paint);
                canvas.drawLine(8,12,11,15,paint); canvas.drawLine(11,15,16,9,paint);
            } else if (kind == 4) {
                canvas.drawCircle(12,12,9,paint); canvas.drawLine(12,11,12,17,paint); canvas.drawPoint(12,7,paint);
            } else if (kind == 6) {
                canvas.drawRoundRect(8,7,20,21,2,2,paint); canvas.drawLine(4,16,4,3,paint); canvas.drawLine(4,3,15,3,paint);
            } else if (kind == 7) { canvas.drawLine(9,6,15,12,paint); canvas.drawLine(15,12,9,18,paint); }
            canvas.restore();
        }
    }
}
