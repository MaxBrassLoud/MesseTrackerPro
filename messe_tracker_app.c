#include <furi.h>
#include <furi_hal.h>
#include <gui/gui.h>
#include <gui/view_dispatcher.h>
#include <gui/scene_manager.h>
#include <gui/modules/submenu.h>
#include <gui/modules/text_input.h>
#include <gui/modules/popup.h>
#include <notification/notification.h>
#include <notification/notification_messages.h>
#include <storage/storage.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define TAG "MesseTracker"
#define APP_DATA_DIR "/ext/apps_data/messe_tracker"
#define DAYS_DIR APP_DATA_DIR "/days"
#define MESSEN_DIR APP_DATA_DIR "/messen"
#define CONFIG_PATH APP_DATA_DIR "/config.txt"
#define STATE_PATH APP_DATA_DIR "/state.txt"

#define MAX_CATEGORIES 16
#define MAX_PRODUCTS 32
#define MAX_MESSEN 16
#define CATEGORY_LEN 32
#define DAY_NAME_LEN 48
#define MESSE_NAME_LEN 32
#define MESSE_DISPLAY_LEN 48
#define CUSTOMER_NAME_LEN 48
#define CUSTOMER_DESC_LEN 64
#define PRODUCT_NAME_LEN 32
#define TEXT_BUF_LEN 64
#define HEADER_BUF_LEN 80
#define LINE_BUF 256
#define MAX_READ_SIZE (64 * 1024)

#define CUSTOM_EVENT_TEXT_INPUT_DONE 100
#define CUSTOM_EVENT_AUTO_OPEN_DAY 101
#define CUSTOM_EVENT_BULK_NEXT 102
#define CUSTOM_EVENT_BULK_FINISH 103

/* =====================================================================
 *  Views
 * ===================================================================== */
typedef enum {
    MyAppViewMainMenu,
    MyAppViewDayMenu,
    MyAppViewCustomerCategory,
    MyAppViewSettings,
    MyAppViewEditCategories,
    MyAppViewCategoryActions,
    MyAppViewConfirmEndDay,
    MyAppViewConfirmToggle,
    MyAppViewTextInput,
    MyAppViewPopup,
    MyAppViewMerchMenu,
    MyAppViewMerchAfterCount,
    MyAppViewProductList,
    MyAppViewProductActions,
    MyAppViewProductDeleteConfirm,
    MyAppViewMesseSelect,
    MyAppViewMesseList,
    MyAppViewMesseActions,
    MyAppViewMesseDeleteConfirm,
    MyAppViewCategoryDeleteConfirm,
    MyAppViewCount,
} MyAppView;

/* =====================================================================
 *  Szenen
 * ===================================================================== */
typedef enum {
    MyAppSceneMainMenu,
    MyAppSceneDayMenu,
    MyAppSceneCustomerCategory,
    MyAppSceneSettings,
    MyAppSceneEditCategories,
    MyAppSceneCategoryActions,
    MyAppSceneConfirmEndDay,
    MyAppSceneConfirmToggle,
    MyAppSceneTextInput,
    MyAppScenePopup,
    MyAppSceneMerchMenu,
    MyAppSceneMerchAfterCount,
    MyAppSceneProductList,
    MyAppSceneProductActions,
    MyAppSceneProductDeleteConfirm,
    MyAppSceneMesseSelect,
    MyAppSceneMesseList,
    MyAppSceneMesseActions,
    MyAppSceneMesseDeleteConfirm,
    MyAppSceneCategoryDeleteConfirm,
    MyAppSceneCount,
} MyAppScene;

/* =====================================================================
 *  Indizes
 * ===================================================================== */
typedef enum {
    MyAppMainMenuIndexNewDay,
    MyAppMainMenuIndexResumeDay,
    MyAppMainMenuIndexSettings,
} MyAppMainMenuIndex;

typedef enum {
    MyAppDayMenuIndexToggle,
    MyAppDayMenuIndexAddCustomer,
    MyAppDayMenuIndexMerch,
    MyAppDayMenuIndexEndDay,
} MyAppDayMenuIndex;

typedef enum {
    MyAppSettingsIndexManageMessen,
    MyAppSettingsIndexEditCategories,
} MyAppSettingsIndex;

typedef enum {
    MyAppCategoryActionsIndexEdit,
    MyAppCategoryActionsIndexDelete,
} MyAppCategoryActionsIndex;

typedef enum {
    MyAppConfirmEndDayIndexYes,
    MyAppConfirmEndDayIndexNo,
} MyAppConfirmEndDayIndex;

typedef enum {
    MyAppConfirmToggleIndexYes,
    MyAppConfirmToggleIndexNo,
} MyAppConfirmToggleIndex;

typedef enum {
    MyAppMerchMenuIndexCountAll,
    MyAppMerchMenuIndexRefillAll,
    MyAppMerchMenuIndexProductList,
} MyAppMerchMenuIndex;

typedef enum {
    MyAppMerchAfterCountIndexYes,
    MyAppMerchAfterCountIndexNo,
} MyAppMerchAfterCountIndex;

typedef enum {
    MyAppProductActionsIndexCount,
    MyAppProductActionsIndexRefill,
    MyAppProductActionsIndexRename,
    MyAppProductActionsIndexDelete,
} MyAppProductActionsIndex;

typedef enum {
    MyAppProductDeleteConfirmIndexYes,
    MyAppProductDeleteConfirmIndexNo,
} MyAppProductDeleteConfirmIndex;

typedef enum {
    MyAppMesseActionsIndexEditProducts,
    MyAppMesseActionsIndexRename,
    MyAppMesseActionsIndexDelete,
} MyAppMesseActionsIndex;

typedef enum {
    MyAppMesseDeleteConfirmIndexYes,
    MyAppMesseDeleteConfirmIndexNo,
} MyAppMesseDeleteConfirmIndex;

typedef enum {
    MyAppCategoryDeleteConfirmIndexYes,
    MyAppCategoryDeleteConfirmIndexNo,
} MyAppCategoryDeleteConfirmIndex;

/* =====================================================================
 *  TextInput-Zwecke
 * ===================================================================== */
typedef enum {
    MyAppTextInputPurposeNone,
    MyAppTextInputPurposeDayName,
    MyAppTextInputPurposeCustomerName,
    MyAppTextInputPurposeCustomerDesc,
    MyAppTextInputPurposeNewCategory,
    MyAppTextInputPurposeEditCategory,
    MyAppTextInputPurposeEndDayConfirm,
    MyAppTextInputPurposeMerchCountBulk,
    MyAppTextInputPurposeMerchRefillBulk,
    MyAppTextInputPurposeMerchInitialBulk,
    MyAppTextInputPurposeMerchCountSingle,
    MyAppTextInputPurposeMerchRefillSingle,
    MyAppTextInputPurposeMerchNewName,
    MyAppTextInputPurposeMerchEditName,
    MyAppTextInputPurposeNewMesseName,
    MyAppTextInputPurposeRenameMesse,
} MyAppTextInputPurpose;

typedef enum {
    MerchBulkNone,
    MerchBulkCount,
    MerchBulkRefill,
    MerchBulkInitial,
} MerchBulkMode;

/* =====================================================================
 *  Popup-Arten
 * ===================================================================== */
typedef enum {
    MyAppPopupKindNone,
    MyAppPopupKindCustomerSaved,
    MyAppPopupKindDayAlreadyActive,
    MyAppPopupKindDayNameExists,
    MyAppPopupKindMerchCountDone,
    MyAppPopupKindMerchRefillDone,
    MyAppPopupKindMerchNoProducts,
    MyAppPopupKindMerchMaxProducts,
    MyAppPopupKindMesseNoProducts,
    MyAppPopupKindNoMessen,
    MyAppPopupKindMesseNameExists,
    MyAppPopupKindMesseSaved,
    MyAppPopupKindErrorEmptyName,
    MyAppPopupKindRefillBelowCurrent,
} MyAppPopupKind;

typedef enum {
    ProductListModeDay,
    ProductListModeMesseEdit,
} ProductListMode;

/* =====================================================================
 *  Strukturen
 * ===================================================================== */
typedef struct {
    char name[PRODUCT_NAME_LEN];
    uint16_t initial;
    uint16_t refilled;
    uint16_t current;
} MerchProduct;

typedef struct {
    Gui* gui;
    NotificationApp* notifications;
    ViewDispatcher* view_dispatcher;
    SceneManager* scene_manager;

    Submenu* main_menu;
    Submenu* day_menu;
    Submenu* customer_category_menu;
    Submenu* settings_menu;
    Submenu* edit_categories_menu;
    Submenu* category_actions_menu;
    Submenu* confirm_end_day_menu;
    Submenu* confirm_toggle_menu;
    Submenu* merch_menu;
    Submenu* merch_after_count_menu;
    Submenu* product_list_menu;
    Submenu* product_actions_menu;
    Submenu* product_delete_confirm_menu;
    Submenu* messe_select_menu;
    Submenu* messe_list_menu;
    Submenu* messe_actions_menu;
    Submenu* messe_delete_confirm_menu;
    Submenu* category_delete_confirm_menu;

    TextInput* text_input;
    Popup* popup;

    char text_buffer[TEXT_BUF_LEN];
    char text_input_header[HEADER_BUF_LEN];
    MyAppTextInputPurpose text_input_purpose;

    /* Aktueller Tag */
    char current_day[DAY_NAME_LEN];
    char current_messe[MESSE_NAME_LEN];
    bool at_booth;
    uint16_t next_customer_id;

    /* Aktueller Kunde (während Anlage) */
    char current_customer[CUSTOMER_NAME_LEN];
    char current_customer_desc[CUSTOMER_DESC_LEN];

    /* Kategorien */
    char categories[MAX_CATEGORIES][CATEGORY_LEN];
    size_t category_count;
    size_t editing_category_index;

    /* Messen */
    char messen[MAX_MESSEN][MESSE_NAME_LEN];
    char messen_display[MAX_MESSEN][MESSE_DISPLAY_LEN];
    size_t messen_count;
    size_t editing_messe_index;
    char pending_messe_name[MESSE_NAME_LEN];
    char pending_messe_display[MESSE_DISPLAY_LEN];

    /* Produkte */
    MerchProduct products[MAX_PRODUCTS];
    size_t product_count;
    size_t editing_product_index;
    size_t merch_bulk_index;
    MerchBulkMode merch_bulk_mode;
    ProductListMode product_list_mode;
    bool merch_add_new_flow;

    bool pending_merch_bulk_continue;
    bool pending_merch_bulk_finish;

    MyAppPopupKind popup_kind;
    bool popup_has_return;
    MyAppScene popup_return_scene;

    bool pending_auto_open_day;
} MyApp;

/* =====================================================================
 *  Forward Declarations
 * ===================================================================== */
static void my_app_main_menu_callback(void*, uint32_t);
static void my_app_day_menu_callback(void*, uint32_t);
static void my_app_customer_category_callback(void*, uint32_t);
static void my_app_settings_callback(void*, uint32_t);
static void my_app_edit_categories_callback(void*, uint32_t);
static void my_app_category_actions_callback(void*, uint32_t);
static void my_app_confirm_end_day_callback(void*, uint32_t);
static void my_app_confirm_toggle_callback(void*, uint32_t);
static void my_app_merch_menu_callback(void*, uint32_t);
static void my_app_merch_after_count_callback(void*, uint32_t);
static void my_app_product_list_callback(void*, uint32_t);
static void my_app_product_actions_callback(void*, uint32_t);
static void my_app_product_delete_confirm_callback(void*, uint32_t);
static void my_app_messe_select_callback(void*, uint32_t);
static void my_app_messe_list_callback(void*, uint32_t);
static void my_app_messe_actions_callback(void*, uint32_t);
static void my_app_messe_delete_confirm_callback(void*, uint32_t);
static void my_app_category_delete_confirm_callback(void*, uint32_t);
static void my_app_text_input_callback(void*);

static void save_categories(MyApp*);
static void save_state(MyApp*);
static void clear_state(void);
static void save_messe(MyApp*);
static void load_messe_products(MyApp*, const char*);
static void merch_bulk_advance_or_finish(MyApp*);
static void create_day_with_initial(MyApp*);

/* =====================================================================
 *  Haptik
 * ===================================================================== */
static void haptic_tap(MyApp* app) {
    if(app->notifications) notification_message(app->notifications, &sequence_single_vibro);
}

/* =====================================================================
 *  Utilities
 * ===================================================================== */
static bool str_equals_ignore_case(const char* a, const char* b) {
    while(*a && *b) {
        char ca = *a, cb = *b;
        if(ca >= 'a' && ca <= 'z') ca -= 32;
        if(cb >= 'a' && cb <= 'z') cb -= 32;
        if(ca != cb) return false;
        a++; b++;
    }
    return *a == '\0' && *b == '\0';
}

static uint16_t parse_uint16_clamped(const char* s) {
    if(!s || !*s) return 0;
    long v = strtol(s, NULL, 10);
    if(v < 0) return 0;
    if(v > 65535) return 65535;
    return (uint16_t)v;
}

/* Erlaubt: A-Z a-z 0-9 - _ ; Leerzeichen wird zu _ */
static bool sanitize_name(const char* in, char* out, size_t out_len) {
    if(!in || !*in) return false;
    size_t j = 0;
    for(size_t i = 0; in[i] && j + 1 < out_len; i++) {
        char c = in[i];
        if(c >= 'a' && c <= 'z') out[j++] = c;
        else if(c >= 'A' && c <= 'Z') out[j++] = c;
        else if(c >= '0' && c <= '9') out[j++] = c;
        else if(c == '-' || c == '_') out[j++] = c;
        else if(c == ' ') out[j++] = '_';
    }
    out[j] = '\0';
    return j > 0;
}

/* Sanitize für Log-Felder: ersetzt Trenn-/Steuerzeichen durch '_' */
static void sanitize_field(const char* in, char* out, size_t out_len) {
    if(out_len == 0) return;
    size_t j = 0;
    for(size_t i = 0; in && in[i] && j + 1 < out_len; i++) {
        char c = in[i];
        if(c == '|' || c == ';' || c == '\n' || c == '\r') c = '_';
        out[j++] = c;
    }
    out[j] = '\0';
}

static void safe_copy(char* dst, const char* src, size_t dst_len) {
    if(dst_len == 0) return;
    if(dst == src) return;
    size_t i = 0;
    for(; i + 1 < dst_len && src && src[i]; i++) dst[i] = src[i];
    dst[i] = '\0';
}

static bool next_field(const char** cursor, char* out, size_t out_len) {
    if(!cursor || !*cursor || !**cursor) return false;
    const char* p = *cursor;
    size_t i = 0;
    while(*p && *p != ';' && i + 1 < out_len) out[i++] = *p++;
    out[i] = '\0';
    if(*p == ';') p++;
    *cursor = p;
    return true;
}

static void ensure_dirs(void) {
    Storage* s = furi_record_open(RECORD_STORAGE);
    storage_common_mkdir(s, APP_DATA_DIR);
    storage_common_mkdir(s, DAYS_DIR);
    storage_common_mkdir(s, MESSEN_DIR);
    furi_record_close(RECORD_STORAGE);
}

/* =====================================================================
 *  Datei-Helfer (heap-basiert, kein Stack-Risiko)
 * ===================================================================== */
static char* read_file_to_string(const char* path, size_t* out_len) {
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    char* buf = NULL;
    if(out_len) *out_len = 0;
    if(storage_file_open(f, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        size_t size = storage_file_size(f);
        if(size > MAX_READ_SIZE) size = MAX_READ_SIZE;
        buf = malloc(size + 1);
        if(buf) {
            size_t total = 0;
            uint16_t n = 0;
            while(total < size &&
                  (n = storage_file_read(f, buf + total, (uint16_t)(size - total))) > 0) {
                total += n;
            }
            buf[total] = '\0';
            if(out_len) *out_len = total;
        }
        storage_file_close(f);
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);
    return buf;
}

/* Atomarer Replace: schreibt tmp erst fertig, benennt alte Datei zu .bak,
 * dann tmp -> final, bei Erfolg .bak löschen, sonst zurückrollen. */
static bool storage_atomic_commit(const char* tmp_path, const char* final_path) {
    Storage* s = furi_record_open(RECORD_STORAGE);
    char bak[300];
    snprintf(bak, sizeof(bak), "%s.bak", final_path);
    storage_common_remove(s, bak);

    bool existed = (storage_common_stat(s, final_path, NULL) == FSE_OK);
    bool ok = false;
    if(existed) {
        if(storage_common_rename(s, final_path, bak) != FSE_OK) {
            furi_record_close(RECORD_STORAGE);
            return false;
        }
    }
    if(storage_common_rename(s, tmp_path, final_path) == FSE_OK) {
        if(existed) storage_common_remove(s, bak);
        ok = true;
    } else {
        if(existed) storage_common_rename(s, bak, final_path);
    }
    furi_record_close(RECORD_STORAGE);
    return ok;
}

static void atomic_write_lines(const char* path, const char* const* lines, size_t count) {
    char tmp[280];
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);

    bool wrote = false;
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    if(storage_file_open(f, tmp, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        bool ok = true;
        for(size_t i = 0; i < count; i++) {
            size_t len = strlen(lines[i]);
            if(storage_file_write(f, lines[i], len) != len) { ok = false; break; }
            if(storage_file_write(f, "\n", 1) != 1) { ok = false; break; }
        }
        storage_file_close(f);
        wrote = ok;
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);

    if(wrote) storage_atomic_commit(tmp, path);
}

/* =====================================================================
 *  Persistenz: Kategorien
 * ===================================================================== */
static void save_categories(MyApp* app) {
    const char* lines[MAX_CATEGORIES];
    for(size_t i = 0; i < app->category_count; i++) lines[i] = app->categories[i];
    atomic_write_lines(CONFIG_PATH, lines, app->category_count);
}

static void load_categories(MyApp* app) {
    app->category_count = 0;
    size_t len = 0;
    char* buf = read_file_to_string(CONFIG_PATH, &len);
    if(buf) {
        char* line = buf;
        char* end = buf + len;
        while(line < end) {
            char* nl = memchr(line, '\n', end - line);
            if(nl) *nl = '\0';
            size_t l = strlen(line);
            if(l > 0 && line[l-1] == '\r') line[l-1] = '\0';
            if(*line && app->category_count < MAX_CATEGORIES) {
                safe_copy(app->categories[app->category_count], line, CATEGORY_LEN);
                app->category_count++;
            }
            if(!nl) break;
            line = nl + 1;
        }
        free(buf);
    }

    if(app->category_count == 0) {
        safe_copy(app->categories[0], "Interessiert", CATEGORY_LEN);
        safe_copy(app->categories[1], "Anfrage", CATEGORY_LEN);
        safe_copy(app->categories[2], "Auftrag", CATEGORY_LEN);
        app->category_count = 3;
        save_categories(app);
    }
}

/* =====================================================================
 *  Persistenz: State
 * ===================================================================== */
static void save_state(MyApp* app) {
    char buf[LINE_BUF];
    snprintf(buf, sizeof(buf),
        "DAY=%s\nMESSE=%s\nAT_BOOTH=%d\nNEXT_ID=%u\n",
        app->current_day, app->current_messe,
        app->at_booth ? 1 : 0, (unsigned)app->next_customer_id);

    char tmp[280];
    snprintf(tmp, sizeof(tmp), "%s.tmp", STATE_PATH);

    bool wrote = false;
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    if(storage_file_open(f, tmp, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        size_t len = strlen(buf);
        wrote = (storage_file_write(f, buf, len) == len);
        storage_file_close(f);
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);

    if(wrote) storage_atomic_commit(tmp, STATE_PATH);
}

static void clear_state(void) {
    Storage* s = furi_record_open(RECORD_STORAGE);
    storage_common_remove(s, STATE_PATH);
    char bak[280];
    snprintf(bak, sizeof(bak), "%s.bak", STATE_PATH);
    storage_common_remove(s, bak);
    furi_record_close(RECORD_STORAGE);
}

static bool load_state(MyApp* app) {
    app->current_day[0] = '\0';
    app->current_messe[0] = '\0';
    app->at_booth = false;
    app->next_customer_id = 1;

    size_t len = 0;
    char* buf = read_file_to_string(STATE_PATH, &len);
    if(!buf) return false;

    char* line = buf;
    char* end = buf + len;
    while(line < end) {
        char* nl = memchr(line, '\n', end - line);
        if(nl) *nl = '\0';
        size_t l = strlen(line);
        if(l > 0 && line[l-1] == '\r') line[l-1] = '\0';

        if(strncmp(line, "DAY=", 4) == 0) safe_copy(app->current_day, line + 4, DAY_NAME_LEN);
        else if(strncmp(line, "MESSE=", 6) == 0) safe_copy(app->current_messe, line + 6, MESSE_NAME_LEN);
        else if(strncmp(line, "AT_BOOTH=", 9) == 0) app->at_booth = (line[9] == '1');
        else if(strncmp(line, "NEXT_ID=", 8) == 0) app->next_customer_id = parse_uint16_clamped(line + 8);

        if(!nl) break;
        line = nl + 1;
    }
    free(buf);
    return (app->current_day[0] != '\0');
}

/* =====================================================================
 *  Persistenz: Messen
 * ===================================================================== */
static void get_messe_path(const char* name, char* out, size_t out_len) {
    snprintf(out, out_len, "%s/%s.txt", MESSEN_DIR, name);
}

static bool messe_exists(const char* name) {
    char path[256];
    get_messe_path(name, path, sizeof(path));
    Storage* s = furi_record_open(RECORD_STORAGE);
    bool ex = (storage_common_stat(s, path, NULL) == FSE_OK);
    furi_record_close(RECORD_STORAGE);
    return ex;
}

/* Liest NAME= aus der ersten Zeile einer Messe-Datei */
static void read_messe_display(const char* filename, char* out, size_t out_len) {
    safe_copy(out, filename, out_len);
    char path[256];
    get_messe_path(filename, path, sizeof(path));

    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    if(storage_file_open(f, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        char buf[160];
        uint16_t n = storage_file_read(f, buf, sizeof(buf) - 1);
        buf[n] = '\0';
        if(strncmp(buf, "NAME=", 5) == 0) {
            char* nl = strchr(buf, '\n');
            if(nl) *nl = '\0';
            char* cr = strchr(buf, '\r');
            if(cr) *cr = '\0';
            safe_copy(out, buf + 5, out_len);
        }
        storage_file_close(f);
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);
}

static size_t list_messen(MyApp* app) {
    size_t count = 0;
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    if(storage_dir_open(f, MESSEN_DIR)) {
        FileInfo info;
        char name[128];
        while(count < MAX_MESSEN && storage_dir_read(f, &info, name, sizeof(name))) {
            if(info.flags & FSF_DIRECTORY) continue;
            char* dot = strrchr(name, '.');
            if(dot) *dot = '\0';
            if(strlen(name) == 0) continue;
            safe_copy(app->messen[count], name, MESSE_NAME_LEN);
            count++;
        }
        storage_dir_close(f);
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);

    /* Sortieren */
    for(size_t i = 0; i < count; i++)
        for(size_t j = i + 1; j < count; j++)
            if(strcmp(app->messen[i], app->messen[j]) > 0) {
                char tmp[MESSE_NAME_LEN];
                safe_copy(tmp, app->messen[i], MESSE_NAME_LEN);
                safe_copy(app->messen[i], app->messen[j], MESSE_NAME_LEN);
                safe_copy(app->messen[j], tmp, MESSE_NAME_LEN);
            }

    /* Anzeigenamen einlesen */
    for(size_t i = 0; i < count; i++)
        read_messe_display(app->messen[i], app->messen_display[i], MESSE_DISPLAY_LEN);

    app->messen_count = count;
    return count;
}

static void save_messe(MyApp* app) {
    char path[256];
    get_messe_path(app->pending_messe_name, path, sizeof(path));
    char tmp[280];
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);

    bool wrote = false;
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    if(storage_file_open(f, tmp, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        bool ok = true;
        char line[LINE_BUF];
        int n = snprintf(line, sizeof(line), "NAME=%s\n", app->pending_messe_display);
        if(n > 0 && storage_file_write(f, line, n) != (size_t)n) ok = false;
        for(size_t i = 0; ok && i < app->product_count; i++) {
            n = snprintf(line, sizeof(line), "PRODUKT %s\n", app->products[i].name);
            if(n > 0 && storage_file_write(f, line, n) != (size_t)n) ok = false;
        }
        storage_file_close(f);
        wrote = ok;
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);

    if(wrote) storage_atomic_commit(tmp, path);
}

static void load_messe_products(MyApp* app, const char* messe_name) {
    app->product_count = 0;
    char path[256];
    get_messe_path(messe_name, path, sizeof(path));

    size_t len = 0;
    char* buf = read_file_to_string(path, &len);
    if(!buf) return;

    char* line = buf;
    char* end = buf + len;
    while(line < end && app->product_count < MAX_PRODUCTS) {
        char* nl = memchr(line, '\n', end - line);
        if(nl) *nl = '\0';
        size_t l = strlen(line);
        if(l > 0 && line[l-1] == '\r') line[l-1] = '\0';

        if(strncmp(line, "PRODUKT ", 8) == 0) {
            MerchProduct* p = &app->products[app->product_count];
            memset(p, 0, sizeof(*p));
            safe_copy(p->name, line + 8, PRODUCT_NAME_LEN);
            if(p->name[0]) app->product_count++;
        }
        if(!nl) break;
        line = nl + 1;
    }
    free(buf);
}

static void delete_messe(const char* name) {
    char path[256];
    get_messe_path(name, path, sizeof(path));
    Storage* s = furi_record_open(RECORD_STORAGE);
    storage_common_remove(s, path);
    char bak[280];
    snprintf(bak, sizeof(bak), "%s.bak", path);
    storage_common_remove(s, bak);
    furi_record_close(RECORD_STORAGE);
}

/* =====================================================================
 *  Tagesdatei
 * ===================================================================== */
static void get_day_path(const char* day_name, char* out, size_t out_len) {
    snprintf(out, out_len, "%s/%s.txt", DAYS_DIR, day_name);
}

static void format_timestamp(char* out, size_t out_len) {
    DateTime dt;
    furi_hal_rtc_get_datetime(&dt);
    snprintf(out, out_len, "%04u-%02u-%02u %02u:%02u:%02u",
             (unsigned)dt.year, (unsigned)dt.month, (unsigned)dt.day,
             (unsigned)dt.hour, (unsigned)dt.minute, (unsigned)dt.second);
}

static void write_log_line(const char* day_name, const char* line) {
    if(!day_name || !day_name[0]) return;
    Storage* s = furi_record_open(RECORD_STORAGE);
    File* f = storage_file_alloc(s);
    char path[256];
    get_day_path(day_name, path, sizeof(path));
    if(storage_file_open(f, path, FSAM_WRITE, FSOM_OPEN_APPEND)) {
        size_t l = strlen(line);
        if(storage_file_write(f, line, l) != l) {
            FURI_LOG_W(TAG, "Logwrite unvollstaendig");
        }
        storage_file_close(f);
    }
    storage_file_free(f);
    furi_record_close(RECORD_STORAGE);
}

/* MERCH-Log: nutzt ';' als Trenner zwischen Name und Wert */
static void log_merch(MyApp* app, const char* action, const char* name, int value) {
    if(app->current_day[0] == '\0') return;
    char line[LINE_BUF];
    snprintf(line, sizeof(line), "MERCH %s %s;%d\n", action, name, value);
    write_log_line(app->current_day, line);
}

static bool day_exists(const char* name) {
    char path[256];
    get_day_path(name, path, sizeof(path));
    Storage* s = furi_record_open(RECORD_STORAGE);
    bool ex = (storage_common_stat(s, path, NULL) == FSE_OK);
    furi_record_close(RECORD_STORAGE);
    return ex;
}

/* Rekonstruiert Produktzustand + next_customer_id aus Tageslog */
static void load_day_products_from_log(MyApp* app) {
    if(app->current_messe[0] == '\0') return;
    load_messe_products(app, app->current_messe);

    char path[256];
    get_day_path(app->current_day, path, sizeof(path));

    size_t len = 0;
    char* buf = read_file_to_string(path, &len);
    if(!buf) return;

    char* line = buf;
    char* end = buf + len;
    while(line < end) {
        char* nl = memchr(line, '\n', end - line);
        if(nl) *nl = '\0';
        size_t l = strlen(line);
        if(l > 0 && line[l-1] == '\r') line[l-1] = '\0';

        if(strncmp(line, "STARTBESTAND ", 13) == 0) {
            const char* p = line + 13;
            char pname[PRODUCT_NAME_LEN], val[16];
            if(next_field(&p, pname, sizeof(pname)) && next_field(&p, val, sizeof(val))) {
                for(size_t i = 0; i < app->product_count; i++) {
                    if(strcmp(app->products[i].name, pname) == 0) {
                        uint16_t v = parse_uint16_clamped(val);
                        app->products[i].initial = v;
                        app->products[i].current = v;
                        app->products[i].refilled = 0;
                        break;
                    }
                }
            }
        } else if(strncmp(line, "MERCH BESTAND ", 14) == 0) {
            const char* p = line + 14;
            char pname[PRODUCT_NAME_LEN], val[16];
            if(next_field(&p, pname, sizeof(pname)) && next_field(&p, val, sizeof(val))) {
                for(size_t i = 0; i < app->product_count; i++) {
                    if(strcmp(app->products[i].name, pname) == 0) {
                        uint16_t v = parse_uint16_clamped(val);
                        /* Falls kein STARTBESTAND bekannt: initial nachziehen */
                        if(app->products[i].initial == 0 &&
                           app->products[i].refilled == 0 &&
                           app->products[i].current == 0) {
                            app->products[i].initial = v;
                        }
                        app->products[i].current = v;
                        break;
                    }
                }
            }
        } else if(strncmp(line, "MERCH NACHGEFUELLT ", 19) == 0) {
            const char* p = line + 19;
            char pname[PRODUCT_NAME_LEN], val[16];
            if(next_field(&p, pname, sizeof(pname)) && next_field(&p, val, sizeof(val))) {
                for(size_t i = 0; i < app->product_count; i++) {
                    if(strcmp(app->products[i].name, pname) == 0) {
                        uint16_t v = parse_uint16_clamped(val);
                        int delta = (int)v - (int)app->products[i].current;
                        if(delta < 0) delta = 0;
                        app->products[i].refilled =
                            (uint16_t)(app->products[i].refilled + delta);
                        app->products[i].current = v;
                        break;
                    }
                }
            }
        } else if(strncmp(line, "KUNDE|#", 7) == 0) {
            /* Höchste bisherige ID finden, damit next_customer_id weiterzählt */
            uint16_t id = parse_uint16_clamped(line + 7);
            if(id >= app->next_customer_id) app->next_customer_id = (uint16_t)(id + 1);
        }

        if(!nl) break;
        line = nl + 1;
    }
    free(buf);
}

/* =====================================================================
 *  Tag-Verwaltung
 * ===================================================================== */
static void create_day_with_initial(MyApp* app) {
    char ts[32];
    format_timestamp(ts, sizeof(ts));
    char line[LINE_BUF];

    snprintf(line, sizeof(line), "MESSE %s\n", app->current_messe);
    write_log_line(app->current_day, line);
    snprintf(line, sizeof(line), "TAG GESTARTET %s\n", ts);
    write_log_line(app->current_day, line);

    for(size_t i = 0; i < app->product_count; i++) {
        snprintf(line, sizeof(line), "STARTBESTAND %s;%u\n",
                 app->products[i].name, (unsigned)app->products[i].initial);
        write_log_line(app->current_day, line);
        app->products[i].current = app->products[i].initial;
        app->products[i].refilled = 0;
    }

    snprintf(line, sizeof(line), "BETRETEN %s\n", ts);
    write_log_line(app->current_day, line);
    app->at_booth = true;
    app->next_customer_id = 1;

    save_state(app);
    haptic_tap(app);
}

static void day_toggle_booth(MyApp* app) {
    char ts[32];
    format_timestamp(ts, sizeof(ts));
    char line[LINE_BUF];
    snprintf(line, sizeof(line), "%s %s\n", app->at_booth ? "VERLASSEN" : "BETRETEN", ts);
    write_log_line(app->current_day, line);
    app->at_booth = !app->at_booth;
    save_state(app);
    haptic_tap(app);
}

static void add_customer(MyApp* app, const char* category) {
    DateTime dt;
    furi_hal_rtc_get_datetime(&dt);
    int total_min = dt.hour * 60 + dt.minute;
    if(dt.second > 0) total_min++;
    int rounded = ((total_min + 14) / 15) * 15;
    int new_hour = rounded / 60;
    int new_min = rounded % 60;
    if(new_hour >= 24) { new_hour = 23; new_min = 45; }

    const char* name = app->current_customer[0] ? app->current_customer : "Anonym";

    char safe_name[CUSTOMER_NAME_LEN];
    char safe_desc[CUSTOMER_DESC_LEN];
    char safe_cat[CATEGORY_LEN];
    sanitize_field(name, safe_name, sizeof(safe_name));
    sanitize_field(app->current_customer_desc, safe_desc, sizeof(safe_desc));
    sanitize_field(category, safe_cat, sizeof(safe_cat));

    char line[LINE_BUF];
    snprintf(line, sizeof(line), "KUNDE|#%04u|%04u-%02u-%02u|%02u:%02u|%s|%s|%s\n",
             (unsigned)app->next_customer_id,
             (unsigned)dt.year, (unsigned)dt.month, (unsigned)dt.day,
             (unsigned)new_hour, (unsigned)new_min,
             safe_cat, safe_name, safe_desc);
    write_log_line(app->current_day, line);

    app->next_customer_id++;
    save_state(app);
}

static void end_day(MyApp* app) {
    char ts[32];
    format_timestamp(ts, sizeof(ts));
    char line[LINE_BUF];
    snprintf(line, sizeof(line), "TAG BEENDET %s\n", ts);
    write_log_line(app->current_day, line);
    app->current_day[0] = '\0';
    app->current_messe[0] = '\0';
    app->at_booth = false;
    app->next_customer_id = 1;
    clear_state();
    haptic_tap(app);
}

/* =====================================================================
 *  Merch-Aktionen
 * ===================================================================== */
static void merch_apply_initial(MyApp* app, size_t idx, int value) {
    if(idx >= app->product_count) return;
    app->products[idx].initial = (uint16_t)value;
    app->products[idx].current = (uint16_t)value;
    app->products[idx].refilled = 0;
}

/* Bestand aufnehmen. Wenn erstmalig: initial nachziehen und mitloggen. */
static void merch_apply_count(MyApp* app, size_t idx, int new_count) {
    if(idx >= app->product_count) return;
    MerchProduct* p = &app->products[idx];
    bool first = (p->initial == 0 && p->refilled == 0 && p->current == 0);
    if(first) {
        p->initial = (uint16_t)new_count;
        p->refilled = 0;
        p->current = (uint16_t)new_count;
        char line[LINE_BUF];
        snprintf(line, sizeof(line), "STARTBESTAND %s;%d\n", p->name, new_count);
        write_log_line(app->current_day, line);
    } else {
        p->current = (uint16_t)new_count;
    }
    log_merch(app, "BESTAND", p->name, new_count);
}

static void merch_apply_refill(MyApp* app, size_t idx, int new_total) {
    if(idx >= app->product_count) return;
    MerchProduct* p = &app->products[idx];
    int delta = new_total - (int)p->current;
    if(delta < 0) delta = 0;
    p->refilled = (uint16_t)(p->refilled + delta);
    p->current = (uint16_t)new_total;
    log_merch(app, "NACHGEFUELLT", p->name, new_total);
}

static void merch_bulk_advance_or_finish(MyApp* app) {
    app->merch_bulk_index++;
    if(app->merch_bulk_index >= app->product_count) {
        app->pending_merch_bulk_finish = true;
    } else {
        app->pending_merch_bulk_continue = true;
    }
    scene_manager_search_and_switch_to_previous_scene(app->scene_manager, MyAppSceneMerchMenu);
}

/* =====================================================================
 *  SZENE: Hauptmenü
 * ===================================================================== */
void my_app_scene_main_menu_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->main_menu);
    submenu_set_header(app->main_menu, "Messe Tracker");

    if(app->current_day[0] != '\0') {
        submenu_add_item(app->main_menu, "Tag fortsetzen", MyAppMainMenuIndexResumeDay,
                         my_app_main_menu_callback, app);
    } else {
        submenu_add_item(app->main_menu, "Neuen Tag starten", MyAppMainMenuIndexNewDay,
                         my_app_main_menu_callback, app);
    }
    submenu_add_item(app->main_menu, "Einstellungen", MyAppMainMenuIndexSettings,
                     my_app_main_menu_callback, app);

    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMainMenu);

    if(app->pending_auto_open_day) {
        app->pending_auto_open_day = false;
        view_dispatcher_send_custom_event(app->view_dispatcher, CUSTOM_EVENT_AUTO_OPEN_DAY);
    }
}

bool my_app_scene_main_menu_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == CUSTOM_EVENT_AUTO_OPEN_DAY) {
            if(app->current_day[0] != '\0')
                scene_manager_next_scene(app->scene_manager, MyAppSceneDayMenu);
            consumed = true;
        } else if(event.event == MyAppMainMenuIndexNewDay) {
            if(app->current_day[0] != '\0') {
                app->popup_kind = MyAppPopupKindDayAlreadyActive;
                app->popup_has_return = true;
                app->popup_return_scene = MyAppSceneMainMenu;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            } else {
                DateTime dt;
                furi_hal_rtc_get_datetime(&dt);
                snprintf(app->text_buffer, TEXT_BUF_LEN, "%04u-%02u-%02u",
                         (unsigned)dt.year, (unsigned)dt.month, (unsigned)dt.day);
                app->text_input_purpose = MyAppTextInputPurposeDayName;
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        } else if(event.event == MyAppMainMenuIndexResumeDay) {
            load_day_products_from_log(app);
            scene_manager_next_scene(app->scene_manager, MyAppSceneDayMenu);
            consumed = true;
        } else if(event.event == MyAppMainMenuIndexSettings) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneSettings);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_main_menu_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Messe-Auswahl
 * ===================================================================== */
void my_app_scene_messe_select_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->messe_select_menu);
    submenu_set_header(app->messe_select_menu, "Messe waehlen");

    list_messen(app);
    if(app->messen_count == 0) {
        submenu_add_item(app->messe_select_menu, "(keine Messen)", 0, NULL, NULL);
    } else {
        for(size_t i = 0; i < app->messen_count; i++) {
            submenu_add_item(app->messe_select_menu,
                             app->messen_display[i], (uint32_t)i,
                             my_app_messe_select_callback, app);
        }
    }
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMesseSelect);
}

bool my_app_scene_messe_select_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event < app->messen_count) {
            safe_copy(app->current_messe, app->messen[event.event], MESSE_NAME_LEN);
            load_messe_products(app, app->current_messe);

            if(app->product_count == 0) {
                app->popup_kind = MyAppPopupKindMesseNoProducts;
                app->popup_has_return = true;
                app->popup_return_scene = MyAppSceneMesseSelect;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            } else {
                app->merch_bulk_mode = MerchBulkInitial;
                app->merch_bulk_index = 0;
                app->text_input_purpose = MyAppTextInputPurposeMerchInitialBulk;
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        }
    } else if(event.type == SceneManagerEventTypeBack) {
        if(app->messen_count == 0) {
            app->popup_kind = MyAppPopupKindNoMessen;
            app->popup_has_return = true;
            app->popup_return_scene = MyAppSceneMainMenu;
            scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_messe_select_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Tages-Menü
 * ===================================================================== */
static void day_menu_rebuild(MyApp* app) {
    submenu_reset(app->day_menu);
    submenu_set_header(app->day_menu, app->current_day);

    submenu_add_item(app->day_menu,
        app->at_booth ? "Stand verlassen" : "Stand betreten",
        MyAppDayMenuIndexToggle, my_app_day_menu_callback, app);
    submenu_add_item(app->day_menu, "Kunde hinzufuegen", MyAppDayMenuIndexAddCustomer,
                     my_app_day_menu_callback, app);
    submenu_add_item(app->day_menu, "Merch", MyAppDayMenuIndexMerch,
                     my_app_day_menu_callback, app);
    submenu_add_item(app->day_menu, "Tag beenden", MyAppDayMenuIndexEndDay,
                     my_app_day_menu_callback, app);
}

void my_app_scene_day_menu_on_enter(void* context) {
    MyApp* app = context;
    day_menu_rebuild(app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewDayMenu);
}

bool my_app_scene_day_menu_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppDayMenuIndexToggle) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneConfirmToggle);
            consumed = true;
        } else if(event.event == MyAppDayMenuIndexAddCustomer) {
            app->current_customer[0] = '\0';
            app->current_customer_desc[0] = '\0';
            app->text_input_purpose = MyAppTextInputPurposeCustomerName;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppDayMenuIndexMerch) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneMerchMenu);
            consumed = true;
        } else if(event.event == MyAppDayMenuIndexEndDay) {
            app->text_input_purpose = MyAppTextInputPurposeEndDayConfirm;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_day_menu_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Bestätigung Stand betreten/verlassen
 * ===================================================================== */
void my_app_scene_confirm_toggle_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->confirm_toggle_menu);
    if(app->at_booth) {
        submenu_set_header(app->confirm_toggle_menu, "Stand verlassen?");
        submenu_add_item(app->confirm_toggle_menu, "Ja, verlassen",
                         MyAppConfirmToggleIndexYes, my_app_confirm_toggle_callback, app);
    } else {
        submenu_set_header(app->confirm_toggle_menu, "Stand betreten?");
        submenu_add_item(app->confirm_toggle_menu, "Ja, betreten",
                         MyAppConfirmToggleIndexYes, my_app_confirm_toggle_callback, app);
    }
    submenu_add_item(app->confirm_toggle_menu, "Nein",
                     MyAppConfirmToggleIndexNo, my_app_confirm_toggle_callback, app);
    submenu_set_selected_item(app->confirm_toggle_menu, MyAppConfirmToggleIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewConfirmToggle);
}

bool my_app_scene_confirm_toggle_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppConfirmToggleIndexYes) {
            day_toggle_booth(app);
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager, MyAppSceneDayMenu);
            consumed = true;
        } else if(event.event == MyAppConfirmToggleIndexNo) {
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager, MyAppSceneDayMenu);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_confirm_toggle_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Kunden-Kategorie
 * ===================================================================== */
void my_app_scene_customer_category_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->customer_category_menu);
    const char* name = app->current_customer[0] ? app->current_customer : "Anonym";
    submenu_set_header(app->customer_category_menu, name);
    for(size_t i = 0; i < app->category_count; i++)
        submenu_add_item(app->customer_category_menu, app->categories[i], (uint32_t)i,
                         my_app_customer_category_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewCustomerCategory);
}

bool my_app_scene_customer_category_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event < app->category_count) {
            add_customer(app, app->categories[event.event]);
            app->popup_kind = MyAppPopupKindCustomerSaved;
            app->popup_has_return = false;
            scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_customer_category_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Merch-Menü
 * ===================================================================== */
void my_app_scene_merch_menu_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->merch_menu);
    submenu_set_header(app->merch_menu, "Merch");
    submenu_add_item(app->merch_menu, "Bestand aufnehmen", MyAppMerchMenuIndexCountAll,
                     my_app_merch_menu_callback, app);
    submenu_add_item(app->merch_menu, "Nachfuellen", MyAppMerchMenuIndexRefillAll,
                     my_app_merch_menu_callback, app);
    submenu_add_item(app->merch_menu, "Produktliste", MyAppMerchMenuIndexProductList,
                     my_app_merch_menu_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMerchMenu);

    if(app->pending_merch_bulk_continue) {
        app->pending_merch_bulk_continue = false;
        view_dispatcher_send_custom_event(app->view_dispatcher, CUSTOM_EVENT_BULK_NEXT);
    } else if(app->pending_merch_bulk_finish) {
        app->pending_merch_bulk_finish = false;
        view_dispatcher_send_custom_event(app->view_dispatcher, CUSTOM_EVENT_BULK_FINISH);
    }
}

bool my_app_scene_merch_menu_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == CUSTOM_EVENT_BULK_NEXT) {
            if(app->merch_bulk_index < app->product_count) {
                if(app->merch_bulk_mode == MerchBulkCount)
                    app->text_input_purpose = MyAppTextInputPurposeMerchCountBulk;
                else
                    app->text_input_purpose = MyAppTextInputPurposeMerchRefillBulk;
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        } else if(event.event == CUSTOM_EVENT_BULK_FINISH) {
            MerchBulkMode finished = app->merch_bulk_mode;
            app->merch_bulk_mode = MerchBulkNone;
            app->popup_kind = (finished == MerchBulkRefill)
                                  ? MyAppPopupKindMerchRefillDone
                                  : MyAppPopupKindMerchCountDone;
            app->popup_has_return = true;
            app->popup_return_scene = MyAppSceneMerchMenu;
            scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            consumed = true;
        } else if(event.event == MyAppMerchMenuIndexCountAll) {
            if(app->product_count == 0) {
                app->popup_kind = MyAppPopupKindMerchNoProducts;
                app->popup_has_return = true;
                app->popup_return_scene = MyAppSceneMerchMenu;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            } else {
                app->merch_bulk_mode = MerchBulkCount;
                app->merch_bulk_index = 0;
                app->text_input_purpose = MyAppTextInputPurposeMerchCountBulk;
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        } else if(event.event == MyAppMerchMenuIndexRefillAll) {
            if(app->product_count == 0) {
                app->popup_kind = MyAppPopupKindMerchNoProducts;
                app->popup_has_return = true;
                app->popup_return_scene = MyAppSceneMerchMenu;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            } else {
                app->merch_bulk_mode = MerchBulkRefill;
                app->merch_bulk_index = 0;
                app->text_input_purpose = MyAppTextInputPurposeMerchRefillBulk;
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        } else if(event.event == MyAppMerchMenuIndexProductList) {
            app->product_list_mode = ProductListModeDay;
            scene_manager_next_scene(app->scene_manager, MyAppSceneProductList);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_merch_menu_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Nachfrage "Nachfüllen?" nach Bestandsaufnahme
 * ===================================================================== */
void my_app_scene_merch_after_count_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->merch_after_count_menu);
    if(app->merch_bulk_index < app->product_count) {
        char h[96];
        snprintf(h, sizeof(h), "Nachfuellen: %s?", app->products[app->merch_bulk_index].name);
        submenu_set_header(app->merch_after_count_menu, h);
    } else {
        submenu_set_header(app->merch_after_count_menu, "Nachfuellen?");
    }
    submenu_add_item(app->merch_after_count_menu, "Ja, jetzt nachfuellen",
                     MyAppMerchAfterCountIndexYes, my_app_merch_after_count_callback, app);
    submenu_add_item(app->merch_after_count_menu, "Nein, weiter",
                     MyAppMerchAfterCountIndexNo, my_app_merch_after_count_callback, app);
    submenu_set_selected_item(app->merch_after_count_menu, MyAppMerchAfterCountIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMerchAfterCount);
}

bool my_app_scene_merch_after_count_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppMerchAfterCountIndexYes) {
            app->merch_bulk_mode = MerchBulkRefill;
            app->text_input_purpose = MyAppTextInputPurposeMerchRefillBulk;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppMerchAfterCountIndexNo) {
            merch_bulk_advance_or_finish(app);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_merch_after_count_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Produktliste
 * ===================================================================== */
static void product_list_rebuild(MyApp* app) {
    submenu_reset(app->product_list_menu);
    if(app->product_list_mode == ProductListModeMesseEdit) {
        char h[MESSE_DISPLAY_LEN + 16];
        snprintf(h, sizeof(h), "Produkte: %s", app->pending_messe_display);
        submenu_set_header(app->product_list_menu, h);
    } else {
        submenu_set_header(app->product_list_menu, "Produkte");
    }

    for(size_t i = 0; i < app->product_count; i++) {
        char label[80];
        if(app->product_list_mode == ProductListModeDay) {
            int total = (int)app->products[i].initial + (int)app->products[i].refilled;
            int current = (int)app->products[i].current;
            int used = total - current;
            if(used < 0) used = 0;
            snprintf(label, sizeof(label), "%s %d/%d/%d",
                     app->products[i].name, used, current, total);
        } else {
            snprintf(label, sizeof(label), "%s", app->products[i].name);
        }
        submenu_add_item(app->product_list_menu, label, (uint32_t)i,
                         my_app_product_list_callback, app);
    }
    if(app->product_count < MAX_PRODUCTS) {
        submenu_add_item(app->product_list_menu, "+ Neues Produkt",
                         (uint32_t)app->product_count, my_app_product_list_callback, app);
    }
}

void my_app_scene_product_list_on_enter(void* context) {
    MyApp* app = context;
    app->merch_add_new_flow = false;
    product_list_rebuild(app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewProductList);
}

bool my_app_scene_product_list_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event < app->product_count) {
            app->editing_product_index = event.event;
            scene_manager_next_scene(app->scene_manager, MyAppSceneProductActions);
            consumed = true;
        } else {
            if(app->product_count >= MAX_PRODUCTS) {
                app->popup_kind = MyAppPopupKindMerchMaxProducts;
                app->popup_has_return = true;
                app->popup_return_scene = MyAppSceneProductList;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
            } else {
                app->text_input_purpose = MyAppTextInputPurposeMerchNewName;
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_product_list_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Produkt-Aktionen
 * ===================================================================== */
void my_app_scene_product_actions_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->product_actions_menu);
    if(app->editing_product_index < app->product_count)
        submenu_set_header(app->product_actions_menu, app->products[app->editing_product_index].name);

    if(app->product_list_mode == ProductListModeDay) {
        submenu_add_item(app->product_actions_menu, "Bestand aufnehmen",
                         MyAppProductActionsIndexCount, my_app_product_actions_callback, app);
        submenu_add_item(app->product_actions_menu, "Nachfuellen",
                         MyAppProductActionsIndexRefill, my_app_product_actions_callback, app);
    } else {
        submenu_add_item(app->product_actions_menu, "Umbenennen",
                         MyAppProductActionsIndexRename, my_app_product_actions_callback, app);
        submenu_add_item(app->product_actions_menu, "Loeschen",
                         MyAppProductActionsIndexDelete, my_app_product_actions_callback, app);
    }
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewProductActions);
}

bool my_app_scene_product_actions_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppProductActionsIndexCount) {
            app->text_input_purpose = MyAppTextInputPurposeMerchCountSingle;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppProductActionsIndexRefill) {
            app->text_input_purpose = MyAppTextInputPurposeMerchRefillSingle;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppProductActionsIndexRename) {
            app->text_input_purpose = MyAppTextInputPurposeMerchEditName;
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppProductActionsIndexDelete) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneProductDeleteConfirm);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_product_actions_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Produkt löschen bestätigen
 * ===================================================================== */
void my_app_scene_product_delete_confirm_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->product_delete_confirm_menu);
    if(app->editing_product_index < app->product_count) {
        char h[80];
        snprintf(h, sizeof(h), "Loeschen: %s?",
                 app->products[app->editing_product_index].name);
        submenu_set_header(app->product_delete_confirm_menu, h);
    } else {
        submenu_set_header(app->product_delete_confirm_menu, "Loeschen?");
    }
    submenu_add_item(app->product_delete_confirm_menu, "Ja, loeschen",
                     MyAppProductDeleteConfirmIndexYes, my_app_product_delete_confirm_callback, app);
    submenu_add_item(app->product_delete_confirm_menu, "Nein",
                     MyAppProductDeleteConfirmIndexNo, my_app_product_delete_confirm_callback, app);
    submenu_set_selected_item(app->product_delete_confirm_menu, MyAppProductDeleteConfirmIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewProductDeleteConfirm);
}

bool my_app_scene_product_delete_confirm_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppProductDeleteConfirmIndexYes) {
            if(app->editing_product_index < app->product_count) {
                log_merch(app, "GELOESCHT", app->products[app->editing_product_index].name, 0);
                for(size_t i = app->editing_product_index; i + 1 < app->product_count; i++)
                    app->products[i] = app->products[i + 1];
                app->product_count--;
                if(app->product_list_mode == ProductListModeMesseEdit) save_messe(app);
                haptic_tap(app);
            }
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                             MyAppSceneProductList);
            consumed = true;
        } else if(event.event == MyAppProductDeleteConfirmIndexNo) {
            scene_manager_previous_scene(app->scene_manager);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_product_delete_confirm_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Bestätigung Tag beenden
 * ===================================================================== */
void my_app_scene_confirm_end_day_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->confirm_end_day_menu);
    submenu_set_header(app->confirm_end_day_menu, "Tag wirklich beenden?");
    submenu_add_item(app->confirm_end_day_menu, "Ja, Tag beenden",
                     MyAppConfirmEndDayIndexYes, my_app_confirm_end_day_callback, app);
    submenu_add_item(app->confirm_end_day_menu, "Nein, abbrechen",
                     MyAppConfirmEndDayIndexNo, my_app_confirm_end_day_callback, app);
    submenu_set_selected_item(app->confirm_end_day_menu, MyAppConfirmEndDayIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewConfirmEndDay);
}

bool my_app_scene_confirm_end_day_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppConfirmEndDayIndexYes) {
            end_day(app);
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager, MyAppSceneMainMenu);
            consumed = true;
        } else if(event.event == MyAppConfirmEndDayIndexNo) {
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager, MyAppSceneDayMenu);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_confirm_end_day_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Popup
 * ===================================================================== */
void my_app_scene_popup_on_enter(void* context) {
    MyApp* app = context;
    popup_reset(app->popup);
    haptic_tap(app);

    switch(app->popup_kind) {
    case MyAppPopupKindCustomerSaved: {
        const char* name = app->current_customer[0] ? app->current_customer : "Anonym";
        char text[160];
        snprintf(text, sizeof(text), "#%04u\n%s\n%s",
                 (unsigned)(app->next_customer_id - 1), name,
                 app->current_customer_desc[0] ? app->current_customer_desc : "");
        popup_set_header(app->popup, "Kunde gespeichert", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, text, 5, 22, AlignLeft, AlignTop);
        break;
    }
    case MyAppPopupKindDayAlreadyActive:
        popup_set_header(app->popup, "Fehler", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Ein Tag ist bereits aktiv.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindDayNameExists:
        popup_set_header(app->popup, "Fehler", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Tag existiert bereits.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindMerchCountDone: {
        DateTime dt; furi_hal_rtc_get_datetime(&dt);
        char text[64];
        snprintf(text, sizeof(text), "Bestand gesichert\num %02u:%02u",
                 (unsigned)dt.hour, (unsigned)dt.minute);
        popup_set_header(app->popup, "Fertig", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, text, 5, 22, AlignLeft, AlignTop);
        break;
    }
    case MyAppPopupKindMerchRefillDone: {
        DateTime dt; furi_hal_rtc_get_datetime(&dt);
        char text[64];
        snprintf(text, sizeof(text), "Nachfuellen fertig\num %02u:%02u",
                 (unsigned)dt.hour, (unsigned)dt.minute);
        popup_set_header(app->popup, "Fertig", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, text, 5, 22, AlignLeft, AlignTop);
        break;
    }
    case MyAppPopupKindMerchNoProducts:
        popup_set_header(app->popup, "Hinweis", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Keine Produkte.\nBitte erst anlegen.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindMerchMaxProducts:
        popup_set_header(app->popup, "Fehler", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Maximale Anzahl\nan Produkten erreicht.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindMesseNoProducts:
        popup_set_header(app->popup, "Hinweis", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Messe hat keine\nProdukte. Erst in\nEinstellungen pflegen.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindNoMessen:
        popup_set_header(app->popup, "Hinweis", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Keine Messe vorhanden.\nBitte in Einstellungen\nanlegen.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindMesseNameExists:
        popup_set_header(app->popup, "Fehler", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Messe existiert bereits.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindMesseSaved:
        popup_set_header(app->popup, "Gespeichert", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Messe angelegt.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindErrorEmptyName:
        popup_set_header(app->popup, "Fehler", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Ungueltiger Name.", 5, 22, AlignLeft, AlignTop);
        break;
    case MyAppPopupKindRefillBelowCurrent:
        popup_set_header(app->popup, "Hinweis", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "Wert kleiner als\naktueller Bestand.\nNicht uebernommen.",
                       5, 22, AlignLeft, AlignTop);
        break;
    default:
        popup_set_header(app->popup, "Info", 64, 3, AlignCenter, AlignTop);
        popup_set_text(app->popup, "", 5, 22, AlignLeft, AlignTop);
        break;
    }
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewPopup);
}

bool my_app_scene_popup_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    if(event.type == SceneManagerEventTypeBack) {
        if(app->popup_kind == MyAppPopupKindCustomerSaved) {
            if(!scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                                  MyAppSceneDayMenu))
                scene_manager_previous_scene(app->scene_manager);
            return true;
        }
        if(app->popup_has_return) {
            app->popup_has_return = false;
            MyAppScene target = app->popup_return_scene;
            if(!scene_manager_search_and_switch_to_previous_scene(app->scene_manager, target))
                scene_manager_previous_scene(app->scene_manager);
        } else {
            scene_manager_previous_scene(app->scene_manager);
        }
        return true;
    }
    return false;
}

void my_app_scene_popup_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Einstellungen
 * ===================================================================== */
void my_app_scene_settings_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->settings_menu);
    submenu_set_header(app->settings_menu, "Einstellungen");
    submenu_add_item(app->settings_menu, "Messen verwalten",
                     MyAppSettingsIndexManageMessen, my_app_settings_callback, app);
    submenu_add_item(app->settings_menu, "Kategorien bearbeiten",
                     MyAppSettingsIndexEditCategories, my_app_settings_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewSettings);
}

bool my_app_scene_settings_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppSettingsIndexManageMessen) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneMesseList);
            consumed = true;
        } else if(event.event == MyAppSettingsIndexEditCategories) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneEditCategories);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_settings_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Messe-Liste
 * ===================================================================== */
void my_app_scene_messe_list_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->messe_list_menu);
    submenu_set_header(app->messe_list_menu, "Messen");

    list_messen(app);
    for(size_t i = 0; i < app->messen_count; i++)
        submenu_add_item(app->messe_list_menu, app->messen_display[i], (uint32_t)i,
                         my_app_messe_list_callback, app);
    submenu_add_item(app->messe_list_menu, "+ Neue Messe",
                     (uint32_t)app->messen_count, my_app_messe_list_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMesseList);
}

bool my_app_scene_messe_list_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event < app->messen_count) {
            app->editing_messe_index = event.event;
            safe_copy(app->pending_messe_name, app->messen[event.event], MESSE_NAME_LEN);
            safe_copy(app->pending_messe_display, app->messen_display[event.event],
                      MESSE_DISPLAY_LEN);
            scene_manager_next_scene(app->scene_manager, MyAppSceneMesseActions);
            consumed = true;
        } else {
            app->text_input_purpose = MyAppTextInputPurposeNewMesseName;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_messe_list_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Messe-Aktionen
 * ===================================================================== */
void my_app_scene_messe_actions_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->messe_actions_menu);
    submenu_set_header(app->messe_actions_menu, app->pending_messe_display);
    submenu_add_item(app->messe_actions_menu, "Produkte bearbeiten",
                     MyAppMesseActionsIndexEditProducts, my_app_messe_actions_callback, app);
    submenu_add_item(app->messe_actions_menu, "Umbenennen",
                     MyAppMesseActionsIndexRename, my_app_messe_actions_callback, app);
    submenu_add_item(app->messe_actions_menu, "Loeschen",
                     MyAppMesseActionsIndexDelete, my_app_messe_actions_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMesseActions);
}

bool my_app_scene_messe_actions_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppMesseActionsIndexEditProducts) {
            load_messe_products(app, app->pending_messe_name);
            app->product_list_mode = ProductListModeMesseEdit;
            scene_manager_next_scene(app->scene_manager, MyAppSceneProductList);
            consumed = true;
        } else if(event.event == MyAppMesseActionsIndexRename) {
            app->text_input_purpose = MyAppTextInputPurposeRenameMesse;
            safe_copy(app->text_buffer, app->pending_messe_display, TEXT_BUF_LEN);
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppMesseActionsIndexDelete) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneMesseDeleteConfirm);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_messe_actions_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Messe löschen bestätigen
 * ===================================================================== */
void my_app_scene_messe_delete_confirm_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->messe_delete_confirm_menu);
    char h[MESSE_DISPLAY_LEN + 20];
    snprintf(h, sizeof(h), "Loeschen: %s?", app->pending_messe_display);
    submenu_set_header(app->messe_delete_confirm_menu, h);
    submenu_add_item(app->messe_delete_confirm_menu, "Ja, loeschen",
                     MyAppMesseDeleteConfirmIndexYes,
                     my_app_messe_delete_confirm_callback, app);
    submenu_add_item(app->messe_delete_confirm_menu, "Nein",
                     MyAppMesseDeleteConfirmIndexNo,
                     my_app_messe_delete_confirm_callback, app);
    submenu_set_selected_item(app->messe_delete_confirm_menu, MyAppMesseDeleteConfirmIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewMesseDeleteConfirm);
}

bool my_app_scene_messe_delete_confirm_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppMesseDeleteConfirmIndexYes) {
            delete_messe(app->pending_messe_name);
            app->pending_messe_name[0] = '\0';
            app->pending_messe_display[0] = '\0';
            haptic_tap(app);
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                             MyAppSceneMesseList);
            consumed = true;
        } else if(event.event == MyAppMesseDeleteConfirmIndexNo) {
            scene_manager_previous_scene(app->scene_manager);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_messe_delete_confirm_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Kategorien bearbeiten
 * ===================================================================== */
void my_app_scene_edit_categories_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->edit_categories_menu);
    submenu_set_header(app->edit_categories_menu, "Kategorien");
    for(size_t i = 0; i < app->category_count; i++)
        submenu_add_item(app->edit_categories_menu, app->categories[i], (uint32_t)i,
                         my_app_edit_categories_callback, app);
    submenu_add_item(app->edit_categories_menu, "+ Neue Kategorie",
                     (uint32_t)app->category_count, my_app_edit_categories_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewEditCategories);
}

bool my_app_scene_edit_categories_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event < app->category_count) {
            app->editing_category_index = event.event;
            scene_manager_next_scene(app->scene_manager, MyAppSceneCategoryActions);
            consumed = true;
        } else {
            app->text_input_purpose = MyAppTextInputPurposeNewCategory;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_edit_categories_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Kategorie-Aktionen
 * ===================================================================== */
void my_app_scene_category_actions_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->category_actions_menu);
    submenu_set_header(app->category_actions_menu, app->categories[app->editing_category_index]);
    submenu_add_item(app->category_actions_menu, "Bearbeiten",
                     MyAppCategoryActionsIndexEdit, my_app_category_actions_callback, app);
    submenu_add_item(app->category_actions_menu, "Loeschen",
                     MyAppCategoryActionsIndexDelete, my_app_category_actions_callback, app);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewCategoryActions);
}

bool my_app_scene_category_actions_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppCategoryActionsIndexEdit) {
            app->text_input_purpose = MyAppTextInputPurposeEditCategory;
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            consumed = true;
        } else if(event.event == MyAppCategoryActionsIndexDelete) {
            scene_manager_next_scene(app->scene_manager, MyAppSceneCategoryDeleteConfirm);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_category_actions_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: Kategorie löschen bestätigen
 * ===================================================================== */
void my_app_scene_category_delete_confirm_on_enter(void* context) {
    MyApp* app = context;
    submenu_reset(app->category_delete_confirm_menu);
    char h[CATEGORY_LEN + 20];
    snprintf(h, sizeof(h), "Loeschen: %s?", app->categories[app->editing_category_index]);
    submenu_set_header(app->category_delete_confirm_menu, h);
    submenu_add_item(app->category_delete_confirm_menu, "Ja, loeschen",
                     MyAppCategoryDeleteConfirmIndexYes,
                     my_app_category_delete_confirm_callback, app);
    submenu_add_item(app->category_delete_confirm_menu, "Nein",
                     MyAppCategoryDeleteConfirmIndexNo,
                     my_app_category_delete_confirm_callback, app);
    submenu_set_selected_item(app->category_delete_confirm_menu, MyAppCategoryDeleteConfirmIndexNo);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewCategoryDeleteConfirm);
}

bool my_app_scene_category_delete_confirm_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;
    if(event.type == SceneManagerEventTypeCustom) {
        if(event.event == MyAppCategoryDeleteConfirmIndexYes) {
            for(size_t i = app->editing_category_index; i + 1 < app->category_count; i++)
                safe_copy(app->categories[i], app->categories[i + 1], CATEGORY_LEN);
            if(app->category_count > 0) app->category_count--;
            save_categories(app);
            haptic_tap(app);
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                             MyAppSceneEditCategories);
            consumed = true;
        } else if(event.event == MyAppCategoryDeleteConfirmIndexNo) {
            scene_manager_previous_scene(app->scene_manager);
            consumed = true;
        }
    }
    return consumed;
}

void my_app_scene_category_delete_confirm_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  SZENE: TextInput
 * ===================================================================== */
void my_app_scene_text_input_on_enter(void* context) {
    MyApp* app = context;
    app->text_input_header[0] = '\0';
    const char* header = "Eingabe:";
    bool clear_default = true;

    /* Numerische Eingaben: Buffer immer frisch, auch nach Popup-Rücksprung */
    switch(app->text_input_purpose) {
    case MyAppTextInputPurposeMerchCountBulk:
    case MyAppTextInputPurposeMerchRefillBulk:
    case MyAppTextInputPurposeMerchInitialBulk:
    case MyAppTextInputPurposeMerchCountSingle:
    case MyAppTextInputPurposeMerchRefillSingle:
        app->text_buffer[0] = '\0';
        break;
    default: break;
    }

    switch(app->text_input_purpose) {
    case MyAppTextInputPurposeDayName:
        header = "Tag (Datum):";
        clear_default = false;
        break;
    case MyAppTextInputPurposeCustomerName:
        header = "Kundenname (leer=Anonym):";
        break;
    case MyAppTextInputPurposeCustomerDesc:
        header = "Beschreibung (optional):";
        break;
    case MyAppTextInputPurposeNewCategory:
        header = "Neue Kategorie:";
        break;
    case MyAppTextInputPurposeEditCategory:
        header = "Kategorie:";
        clear_default = false;
        safe_copy(app->text_buffer, app->categories[app->editing_category_index], TEXT_BUF_LEN);
        break;
    case MyAppTextInputPurposeEndDayConfirm:
        header = "Zum Beenden 'ENDE' eingeben:";
        break;
    case MyAppTextInputPurposeMerchCountBulk:
        if(app->merch_bulk_index < app->product_count)
            snprintf(app->text_input_header, HEADER_BUF_LEN, "Bestand: %s",
                     app->products[app->merch_bulk_index].name);
        else safe_copy(app->text_input_header, "Bestand:", HEADER_BUF_LEN);
        header = app->text_input_header;
        break;
    case MyAppTextInputPurposeMerchRefillBulk:
        if(app->merch_bulk_index < app->product_count)
            snprintf(app->text_input_header, HEADER_BUF_LEN, "Neu: %s",
                     app->products[app->merch_bulk_index].name);
        else safe_copy(app->text_input_header, "Neu:", HEADER_BUF_LEN);
        header = app->text_input_header;
        break;
    case MyAppTextInputPurposeMerchInitialBulk:
        if(app->merch_bulk_index < app->product_count)
            snprintf(app->text_input_header, HEADER_BUF_LEN, "Start: %s",
                     app->products[app->merch_bulk_index].name);
        else safe_copy(app->text_input_header, "Start:", HEADER_BUF_LEN);
        header = app->text_input_header;
        break;
    case MyAppTextInputPurposeMerchCountSingle:
        if(app->editing_product_index < app->product_count)
            snprintf(app->text_input_header, HEADER_BUF_LEN, "Bestand: %s",
                     app->products[app->editing_product_index].name);
        else safe_copy(app->text_input_header, "Bestand:", HEADER_BUF_LEN);
        header = app->text_input_header;
        break;
    case MyAppTextInputPurposeMerchRefillSingle:
        if(app->editing_product_index < app->product_count)
            snprintf(app->text_input_header, HEADER_BUF_LEN, "Neu: %s",
                     app->products[app->editing_product_index].name);
        else safe_copy(app->text_input_header, "Neu:", HEADER_BUF_LEN);
        header = app->text_input_header;
        break;
    case MyAppTextInputPurposeMerchNewName:
        header = "Produktname:";
        break;
    case MyAppTextInputPurposeMerchEditName:
        header = "Neuer Name:";
        clear_default = false;
        if(app->editing_product_index < app->product_count)
            safe_copy(app->text_buffer,
                      app->products[app->editing_product_index].name, TEXT_BUF_LEN);
        break;
    case MyAppTextInputPurposeNewMesseName:
        header = "Messe-Name:";
        break;
    case MyAppTextInputPurposeRenameMesse:
        header = "Neuer Messe-Name:";
        clear_default = false;
        break;
    default: break;
    }

    text_input_reset(app->text_input);
    text_input_set_result_callback(app->text_input, my_app_text_input_callback, app,
                                   app->text_buffer, TEXT_BUF_LEN, clear_default);
    text_input_set_header_text(app->text_input, header);
    view_dispatcher_switch_to_view(app->view_dispatcher, MyAppViewTextInput);
}

bool my_app_scene_text_input_on_event(void* context, SceneManagerEvent event) {
    MyApp* app = context;
    bool consumed = false;

    if(event.type == SceneManagerEventTypeBack) {
        if(app->text_input_purpose == MyAppTextInputPurposeMerchCountBulk ||
           app->text_input_purpose == MyAppTextInputPurposeMerchRefillBulk) {
            app->merch_bulk_mode = MerchBulkNone;
            app->merch_bulk_index = 0;
            app->pending_merch_bulk_continue = false;
            app->pending_merch_bulk_finish = false;
        } else if(app->text_input_purpose == MyAppTextInputPurposeMerchInitialBulk) {
            app->current_day[0] = '\0';
            app->current_messe[0] = '\0';
            app->merch_bulk_mode = MerchBulkNone;
            app->merch_bulk_index = 0;
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                             MyAppSceneMainMenu);
            return true;
        }
        return false;
    }

    if(event.type == SceneManagerEventTypeCustom &&
       event.event == CUSTOM_EVENT_TEXT_INPUT_DONE) {
        switch(app->text_input_purpose) {
        case MyAppTextInputPurposeDayName: {
            char sanitized[DAY_NAME_LEN];
            if(!sanitize_name(app->text_buffer, sanitized, sizeof(sanitized))) {
                app->popup_kind = MyAppPopupKindErrorEmptyName;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            if(day_exists(sanitized)) {
                app->popup_kind = MyAppPopupKindDayNameExists;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            safe_copy(app->current_day, sanitized, DAY_NAME_LEN);
            scene_manager_next_scene(app->scene_manager, MyAppSceneMesseSelect);
            break;
        }

        case MyAppTextInputPurposeCustomerName:
            safe_copy(app->current_customer, app->text_buffer, CUSTOMER_NAME_LEN);
            app->text_input_purpose = MyAppTextInputPurposeCustomerDesc;
            app->text_buffer[0] = '\0';
            scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            break;

        case MyAppTextInputPurposeCustomerDesc:
            safe_copy(app->current_customer_desc, app->text_buffer, CUSTOMER_DESC_LEN);
            scene_manager_next_scene(app->scene_manager, MyAppSceneCustomerCategory);
            break;

        case MyAppTextInputPurposeEndDayConfirm:
            if(str_equals_ignore_case(app->text_buffer, "ENDE"))
                scene_manager_next_scene(app->scene_manager, MyAppSceneConfirmEndDay);
            else
                scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                                  MyAppSceneDayMenu);
            break;

        case MyAppTextInputPurposeNewCategory:
            if(strlen(app->text_buffer) > 0 && app->category_count < MAX_CATEGORIES) {
                char safe[CATEGORY_LEN];
                sanitize_field(app->text_buffer, safe, sizeof(safe));
                safe_copy(app->categories[app->category_count], safe, CATEGORY_LEN);
                app->category_count++;
                save_categories(app);
                haptic_tap(app);
            }
            scene_manager_previous_scene(app->scene_manager);
            break;

        case MyAppTextInputPurposeEditCategory:
            if(strlen(app->text_buffer) > 0) {
                char safe[CATEGORY_LEN];
                sanitize_field(app->text_buffer, safe, sizeof(safe));
                safe_copy(app->categories[app->editing_category_index], safe, CATEGORY_LEN);
                save_categories(app);
                haptic_tap(app);
            }
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                              MyAppSceneEditCategories);
            break;

        case MyAppTextInputPurposeMerchCountBulk: {
            uint16_t val = parse_uint16_clamped(app->text_buffer);
            merch_apply_count(app, app->merch_bulk_index, (int)val);
            scene_manager_next_scene(app->scene_manager, MyAppSceneMerchAfterCount);
            break;
        }
        case MyAppTextInputPurposeMerchRefillBulk: {
            uint16_t val = parse_uint16_clamped(app->text_buffer);
            if(app->merch_bulk_index < app->product_count &&
               val < app->products[app->merch_bulk_index].current) {
                app->merch_bulk_mode = MerchBulkNone;
                app->merch_bulk_index = 0;
                app->pending_merch_bulk_continue = false;
                app->pending_merch_bulk_finish = false;
                app->popup_kind = MyAppPopupKindRefillBelowCurrent;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            merch_apply_refill(app, app->merch_bulk_index, (int)val);
            merch_bulk_advance_or_finish(app);
            break;
        }
        case MyAppTextInputPurposeMerchInitialBulk: {
            uint16_t val = parse_uint16_clamped(app->text_buffer);
            merch_apply_initial(app, app->merch_bulk_index, (int)val);
            app->merch_bulk_index++;
            if(app->merch_bulk_index >= app->product_count) {
                create_day_with_initial(app);
                app->merch_bulk_mode = MerchBulkNone;
                app->merch_bulk_index = 0;
                scene_manager_next_scene(app->scene_manager, MyAppSceneDayMenu);
            } else {
                app->text_buffer[0] = '\0';
                scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
            }
            break;
        }

        case MyAppTextInputPurposeMerchCountSingle: {
            uint16_t val = parse_uint16_clamped(app->text_buffer);
            merch_apply_count(app, app->editing_product_index, (int)val);
            if(app->merch_add_new_flow) {
                app->merch_add_new_flow = false;
                if(app->product_list_mode == ProductListModeMesseEdit) save_messe(app);
                scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                                  MyAppSceneProductList);
            } else {
                scene_manager_previous_scene(app->scene_manager);
            }
            break;
        }
        case MyAppTextInputPurposeMerchRefillSingle: {
            uint16_t val = parse_uint16_clamped(app->text_buffer);
            if(app->editing_product_index < app->product_count &&
               val < app->products[app->editing_product_index].current) {
                app->popup_kind = MyAppPopupKindRefillBelowCurrent;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            merch_apply_refill(app, app->editing_product_index, (int)val);
            scene_manager_previous_scene(app->scene_manager);
            break;
        }
        case MyAppTextInputPurposeMerchNewName:
            if(strlen(app->text_buffer) > 0 && app->product_count < MAX_PRODUCTS) {
                MerchProduct* p = &app->products[app->product_count];
                memset(p, 0, sizeof(MerchProduct));
                char safe[PRODUCT_NAME_LEN];
                sanitize_field(app->text_buffer, safe, sizeof(safe));
                safe_copy(p->name, safe, PRODUCT_NAME_LEN);
                app->product_count++;

                if(app->product_list_mode == ProductListModeMesseEdit) {
                    save_messe(app);
                    haptic_tap(app);
                    scene_manager_previous_scene(app->scene_manager);
                } else {
                    log_merch(app, "NEU", p->name, 0);
                    app->editing_product_index = app->product_count - 1;
                    app->merch_add_new_flow = true;
                    app->text_input_purpose = MyAppTextInputPurposeMerchCountSingle;
                    app->text_buffer[0] = '\0';
                    scene_manager_next_scene(app->scene_manager, MyAppSceneTextInput);
                }
            } else {
                scene_manager_previous_scene(app->scene_manager);
            }
            break;
        case MyAppTextInputPurposeMerchEditName:
            if(strlen(app->text_buffer) > 0 &&
               app->editing_product_index < app->product_count) {
                MerchProduct* p = &app->products[app->editing_product_index];
                char safe[PRODUCT_NAME_LEN];
                sanitize_field(app->text_buffer, safe, sizeof(safe));
                safe_copy(p->name, safe, PRODUCT_NAME_LEN);
                if(app->product_list_mode == ProductListModeMesseEdit) {
                    save_messe(app);
                } else {
                    log_merch(app, "UMBENANNT", p->name, 0);
                }
                haptic_tap(app);
            }
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                              MyAppSceneProductList);
            break;

        case MyAppTextInputPurposeNewMesseName: {
            char sanitized[MESSE_NAME_LEN];
            if(!sanitize_name(app->text_buffer, sanitized, sizeof(sanitized))) {
                app->popup_kind = MyAppPopupKindErrorEmptyName;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            if(messe_exists(sanitized)) {
                app->popup_kind = MyAppPopupKindMesseNameExists;
                app->popup_has_return = false;
                scene_manager_next_scene(app->scene_manager, MyAppScenePopup);
                break;
            }
            safe_copy(app->pending_messe_name, sanitized, MESSE_NAME_LEN);
            char safe_disp[MESSE_DISPLAY_LEN];
            sanitize_field(app->text_buffer, safe_disp, sizeof(safe_disp));
            safe_copy(app->pending_messe_display, safe_disp, MESSE_DISPLAY_LEN);
            app->product_count = 0;
            save_messe(app);
            haptic_tap(app);
            scene_manager_next_scene(app->scene_manager, MyAppSceneMesseActions);
            break;
        }
        case MyAppTextInputPurposeRenameMesse: {
            if(strlen(app->text_buffer) == 0) {
                scene_manager_previous_scene(app->scene_manager);
                break;
            }
            char safe_disp[MESSE_DISPLAY_LEN];
            sanitize_field(app->text_buffer, safe_disp, sizeof(safe_disp));
            safe_copy(app->pending_messe_display, safe_disp, MESSE_DISPLAY_LEN);
            save_messe(app);
            haptic_tap(app);
            scene_manager_search_and_switch_to_previous_scene(app->scene_manager,
                                                              MyAppSceneMesseList);
            break;
        }

        default:
            scene_manager_previous_scene(app->scene_manager);
            break;
        }
        consumed = true;
    }
    return consumed;
}

void my_app_scene_text_input_on_exit(void* context) { UNUSED(context); }

/* =====================================================================
 *  Callbacks
 * ===================================================================== */
static void send_event(MyApp* app, uint32_t index) {
    view_dispatcher_send_custom_event(app->view_dispatcher, index);
}
static void my_app_main_menu_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_day_menu_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_customer_category_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_settings_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_edit_categories_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_category_actions_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_confirm_end_day_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_confirm_toggle_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_merch_menu_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_merch_after_count_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_product_list_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_product_actions_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_product_delete_confirm_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_messe_select_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_messe_list_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_messe_actions_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_messe_delete_confirm_callback(void* c, uint32_t i) { send_event(c, i); }
static void my_app_category_delete_confirm_callback(void* c, uint32_t i) { send_event(c, i); }

static void my_app_text_input_callback(void* context) {
    MyApp* app = context;
    view_dispatcher_send_custom_event(app->view_dispatcher, CUSTOM_EVENT_TEXT_INPUT_DONE);
}

/* =====================================================================
 *  SceneManager Tabellen
 * ===================================================================== */
static const AppSceneOnEnterCallback my_app_scene_on_enter_handlers[] = {
    my_app_scene_main_menu_on_enter,
    my_app_scene_day_menu_on_enter,
    my_app_scene_customer_category_on_enter,
    my_app_scene_settings_on_enter,
    my_app_scene_edit_categories_on_enter,
    my_app_scene_category_actions_on_enter,
    my_app_scene_confirm_end_day_on_enter,
    my_app_scene_confirm_toggle_on_enter,
    my_app_scene_text_input_on_enter,
    my_app_scene_popup_on_enter,
    my_app_scene_merch_menu_on_enter,
    my_app_scene_merch_after_count_on_enter,
    my_app_scene_product_list_on_enter,
    my_app_scene_product_actions_on_enter,
    my_app_scene_product_delete_confirm_on_enter,
    my_app_scene_messe_select_on_enter,
    my_app_scene_messe_list_on_enter,
    my_app_scene_messe_actions_on_enter,
    my_app_scene_messe_delete_confirm_on_enter,
    my_app_scene_category_delete_confirm_on_enter,
};

static const AppSceneOnEventCallback my_app_scene_on_event_handlers[] = {
    my_app_scene_main_menu_on_event,
    my_app_scene_day_menu_on_event,
    my_app_scene_customer_category_on_event,
    my_app_scene_settings_on_event,
    my_app_scene_edit_categories_on_event,
    my_app_scene_category_actions_on_event,
    my_app_scene_confirm_end_day_on_event,
    my_app_scene_confirm_toggle_on_event,
    my_app_scene_text_input_on_event,
    my_app_scene_popup_on_event,
    my_app_scene_merch_menu_on_event,
    my_app_scene_merch_after_count_on_event,
    my_app_scene_product_list_on_event,
    my_app_scene_product_actions_on_event,
    my_app_scene_product_delete_confirm_on_event,
    my_app_scene_messe_select_on_event,
    my_app_scene_messe_list_on_event,
    my_app_scene_messe_actions_on_event,
    my_app_scene_messe_delete_confirm_on_event,
    my_app_scene_category_delete_confirm_on_event,
};

static const AppSceneOnExitCallback my_app_scene_on_exit_handlers[] = {
    my_app_scene_main_menu_on_exit,
    my_app_scene_day_menu_on_exit,
    my_app_scene_customer_category_on_exit,
    my_app_scene_settings_on_exit,
    my_app_scene_edit_categories_on_exit,
    my_app_scene_category_actions_on_exit,
    my_app_scene_confirm_end_day_on_exit,
    my_app_scene_confirm_toggle_on_exit,
    my_app_scene_text_input_on_exit,
    my_app_scene_popup_on_exit,
    my_app_scene_merch_menu_on_exit,
    my_app_scene_merch_after_count_on_exit,
    my_app_scene_product_list_on_exit,
    my_app_scene_product_actions_on_exit,
    my_app_scene_product_delete_confirm_on_exit,
    my_app_scene_messe_select_on_exit,
    my_app_scene_messe_list_on_exit,
    my_app_scene_messe_actions_on_exit,
    my_app_scene_messe_delete_confirm_on_exit,
    my_app_scene_category_delete_confirm_on_exit,
};

static const SceneManagerHandlers my_app_scene_manager_handlers = {
    .on_enter_handlers = my_app_scene_on_enter_handlers,
    .on_event_handlers = my_app_scene_on_event_handlers,
    .on_exit_handlers = my_app_scene_on_exit_handlers,
    .scene_num = MyAppSceneCount,
};

/* =====================================================================
 *  ViewDispatcher
 * ===================================================================== */
static bool my_app_custom_event_callback(void* context, uint32_t event) {
    MyApp* app = context;
    return scene_manager_handle_custom_event(app->scene_manager, event);
}
static bool my_app_back_event_callback(void* context) {
    MyApp* app = context;
    return scene_manager_handle_back_event(app->scene_manager);
}

/* =====================================================================
 *  Alloc / Free
 * ===================================================================== */
static MyApp* my_app_alloc(void) {
    MyApp* app = malloc(sizeof(MyApp));
    memset(app, 0, sizeof(MyApp));

    app->gui = furi_record_open(RECORD_GUI);
    app->notifications = furi_record_open(RECORD_NOTIFICATION);

    app->view_dispatcher = view_dispatcher_alloc();
    view_dispatcher_attach_to_gui(app->view_dispatcher, app->gui, ViewDispatcherTypeFullscreen);
    app->scene_manager = scene_manager_alloc(&my_app_scene_manager_handlers, app);

    app->main_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMainMenu, submenu_get_view(app->main_menu));

    app->day_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewDayMenu, submenu_get_view(app->day_menu));

    app->customer_category_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewCustomerCategory,
                             submenu_get_view(app->customer_category_menu));

    app->settings_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewSettings, submenu_get_view(app->settings_menu));

    app->edit_categories_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewEditCategories,
                             submenu_get_view(app->edit_categories_menu));

    app->category_actions_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewCategoryActions,
                             submenu_get_view(app->category_actions_menu));

    app->confirm_end_day_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewConfirmEndDay,
                             submenu_get_view(app->confirm_end_day_menu));

    app->confirm_toggle_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewConfirmToggle,
                             submenu_get_view(app->confirm_toggle_menu));

    app->merch_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMerchMenu, submenu_get_view(app->merch_menu));

    app->merch_after_count_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMerchAfterCount,
                             submenu_get_view(app->merch_after_count_menu));

    app->product_list_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewProductList,
                             submenu_get_view(app->product_list_menu));

    app->product_actions_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewProductActions,
                             submenu_get_view(app->product_actions_menu));

    app->product_delete_confirm_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewProductDeleteConfirm,
                             submenu_get_view(app->product_delete_confirm_menu));

    app->messe_select_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMesseSelect,
                             submenu_get_view(app->messe_select_menu));

    app->messe_list_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMesseList,
                             submenu_get_view(app->messe_list_menu));

    app->messe_actions_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMesseActions,
                             submenu_get_view(app->messe_actions_menu));

    app->messe_delete_confirm_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewMesseDeleteConfirm,
                             submenu_get_view(app->messe_delete_confirm_menu));

    app->category_delete_confirm_menu = submenu_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewCategoryDeleteConfirm,
                             submenu_get_view(app->category_delete_confirm_menu));

    app->text_input = text_input_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewTextInput,
                             text_input_get_view(app->text_input));

    app->popup = popup_alloc();
    view_dispatcher_add_view(app->view_dispatcher, MyAppViewPopup, popup_get_view(app->popup));

    view_dispatcher_set_event_callback_context(app->view_dispatcher, app);
    view_dispatcher_set_custom_event_callback(app->view_dispatcher, my_app_custom_event_callback);
    view_dispatcher_set_navigation_event_callback(app->view_dispatcher, my_app_back_event_callback);

    return app;
}

static void my_app_free(MyApp* app) {
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMainMenu);
    submenu_free(app->main_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewDayMenu);
    submenu_free(app->day_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewCustomerCategory);
    submenu_free(app->customer_category_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewSettings);
    submenu_free(app->settings_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewEditCategories);
    submenu_free(app->edit_categories_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewCategoryActions);
    submenu_free(app->category_actions_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewConfirmEndDay);
    submenu_free(app->confirm_end_day_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewConfirmToggle);
    submenu_free(app->confirm_toggle_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMerchMenu);
    submenu_free(app->merch_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMerchAfterCount);
    submenu_free(app->merch_after_count_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewProductList);
    submenu_free(app->product_list_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewProductActions);
    submenu_free(app->product_actions_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewProductDeleteConfirm);
    submenu_free(app->product_delete_confirm_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMesseSelect);
    submenu_free(app->messe_select_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMesseList);
    submenu_free(app->messe_list_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMesseActions);
    submenu_free(app->messe_actions_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewMesseDeleteConfirm);
    submenu_free(app->messe_delete_confirm_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewCategoryDeleteConfirm);
    submenu_free(app->category_delete_confirm_menu);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewTextInput);
    text_input_free(app->text_input);
    view_dispatcher_remove_view(app->view_dispatcher, MyAppViewPopup);
    popup_free(app->popup);

    scene_manager_free(app->scene_manager);
    view_dispatcher_free(app->view_dispatcher);
    furi_record_close(RECORD_NOTIFICATION);
    furi_record_close(RECORD_GUI);
    free(app);
}

/* =====================================================================
 *  Entry
 * ===================================================================== */
int32_t messe_tracker_app(void* p) {
    UNUSED(p);
    FURI_LOG_I(TAG, "App startet");

    ensure_dirs();
    MyApp* app = my_app_alloc();
    load_categories(app);

    if(load_state(app)) {
        if(!day_exists(app->current_day)) {
            FURI_LOG_W(TAG, "State referenziert fehlenden Tag '%s', verwerfe State",
                       app->current_day);
            clear_state();
            app->current_day[0] = '\0';
            app->current_messe[0] = '\0';
            app->at_booth = false;
            app->next_customer_id = 1;
        } else {
            FURI_LOG_I(TAG, "Aktiver Tag: %s (Messe: %s)",
                       app->current_day, app->current_messe);
            load_day_products_from_log(app);
            app->pending_auto_open_day = true;
        }
    } else {
        FURI_LOG_I(TAG, "Kein aktiver Tag");
    }

    scene_manager_next_scene(app->scene_manager, MyAppSceneMainMenu);
    view_dispatcher_run(app->view_dispatcher);

    my_app_free(app);
    return 0;
}