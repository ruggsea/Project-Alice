#pragma once
// Headless map screenshots (-shot DATE MODE OUT.png): draws the map with the game's own renderer (shaders, textures,
// borders, map modes) into an EGL pbuffer on Mesa's surfaceless platform (software llvmpipe, no display, no GPU) and
// writes it as a PNG. Only built with -DALICE_HEADLESS_SHOTS=ON (needs libEGL); parse_map_mode is always available.
#include <chrono>
#include <cstdio>
#include <string>
#include <vector>
namespace headless {
struct shot_request {
	std::string date; // YYYY-MM-DD; taken when the run reaches it
	map_mode::mode mode;
	std::string path;
};


// -shotcolors FILE: paint every land province with a colour from FILE ("province,RRGGBB" per line, province = the dump's
// index, land provinces first) instead of the map mode's colours; one colour per province, so no stripes. Unlisted = grey.
inline std::string shot_colors_file;

inline bool parse_map_mode(std::string const& name, map_mode::mode& out) {
	static const std::pair<char const*, map_mode::mode> table[] = {
		{"terrain", map_mode::mode::terrain}, {"political", map_mode::mode::political},
		{"revolt", map_mode::mode::revolt}, {"diplomatic", map_mode::mode::diplomatic},
		{"region", map_mode::mode::region}, {"infrastructure", map_mode::mode::infrastructure},
		{"colonial", map_mode::mode::colonial}, {"admin", map_mode::mode::admin},
		{"rgo_output", map_mode::mode::rgo_output}, {"population", map_mode::mode::population},
		{"nationality", map_mode::mode::nationality}, {"sphere", map_mode::mode::sphere},
		{"rank", map_mode::mode::rank}, {"migration", map_mode::mode::migration},
		{"civilization_level", map_mode::mode::civilization_level}, {"crisis", map_mode::mode::crisis},
		{"religion", map_mode::mode::religion}, {"ideology", map_mode::mode::ideology},
		{"income", map_mode::mode::income}, {"consciousness", map_mode::mode::conciousness},
		{"militancy", map_mode::mode::militancy}, {"literacy", map_mode::mode::literacy},
		{"employment", map_mode::mode::employment}, {"factories", map_mode::mode::factories},
		{"issues", map_mode::mode::issues}, {"growth", map_mode::mode::growth},
		{"life_needs", map_mode::mode::life_needs}, {"life_rating", map_mode::mode::life_rating},
	};
	for(auto& [n, m] : table) {
		if(name == n) {
			out = m;
			return true;
		}
	}
	return false;
}

} // namespace headless

#ifdef ALICE_HEADLESS_SHOTS
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include "stb_image_write.h"

namespace ogl {
void load_special_icons(sys::state& state); // defined in opengl_wrapper.cpp, not in its header
}

namespace headless {

// One-time: EGL context + the GL half of ogl::initialize_opengl (which otherwise needs a GLFW window).
inline void init_offscreen_gl(sys::state& state, int width, int height) {
	static bool done = false;
	if(done)
		return;
	done = true;
	// llvmpipe stops at GL 4.5; Alice's shaders declare GLSL 4.60 but use nothing newer, so let Mesa accept it
	setenv("MESA_GL_VERSION_OVERRIDE", "4.6", 0);
	setenv("MESA_GLSL_VERSION_OVERRIDE", "460", 0);
	setenv("EGL_LOG_LEVEL", "fatal", 0); // silence the /dev/dri permission warnings
	auto get_platform_display = (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
	EGLDisplay display = get_platform_display ? get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr)
		: eglGetDisplay(EGL_DEFAULT_DISPLAY);
	EGLint major = 0, minor = 0;
	if(display == EGL_NO_DISPLAY || !eglInitialize(display, &major, &minor)) {
		fprintf(stderr, "screenshot: no EGL display (error 0x%x)\n", eglGetError());
		std::exit(2);
	}
	EGLint const config_attribs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
		EGL_ALPHA_SIZE, 8, EGL_DEPTH_SIZE, 24, EGL_STENCIL_SIZE, 8, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE};
	EGLConfig config;
	EGLint n_configs = 0;
	if(!eglChooseConfig(display, config_attribs, &config, 1, &n_configs) || n_configs < 1) {
		fprintf(stderr, "screenshot: no pbuffer-capable EGL config (error 0x%x)\n", eglGetError());
		std::exit(2);
	}
	EGLint const pbuffer_attribs[] = {EGL_WIDTH, width, EGL_HEIGHT, height, EGL_NONE};
	EGLSurface surface = eglCreatePbufferSurface(display, config, pbuffer_attribs);
	eglBindAPI(EGL_OPENGL_API);
	EGLint const context_attribs[] = {EGL_CONTEXT_MAJOR_VERSION, 4, EGL_CONTEXT_MINOR_VERSION, 5,
		EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
	EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attribs);
	if(surface == EGL_NO_SURFACE || context == EGL_NO_CONTEXT || !eglMakeCurrent(display, surface, surface, context)) {
		fprintf(stderr, "screenshot: EGL surface/context failed (error 0x%x)\n", eglGetError());
		std::exit(2);
	}
	// GLEW is built for GLX: it loads the core GL entry points first, then fails only on the missing X display.
	GLenum glew = glewInit();
	if(glew != GLEW_OK && glew != GLEW_ERROR_NO_GLX_DISPLAY) {
		fprintf(stderr, "screenshot: glewInit failed (%d)\n", int(glew));
		std::exit(2);
	}
	printf("SCREENSHOT gl: EGL %d.%d, %s / %s\n", major, minor, (char const*)glGetString(GL_RENDERER),
			(char const*)glGetString(GL_VERSION));

	glProvokingVertex(GL_FIRST_VERTEX_CONVENTION);
	glEnable(GL_LINE_SMOOTH);
	ogl::load_shaders(state);
	ogl::load_global_squares(state);
	state.open_gl.asset_textures.resize(state.ui_defs.textures.size()
		+ (state.world.national_identity_size() + 1) * state.world.government_flag_size());
	state.map_state.load_map(state);
	ogl::load_special_icons(state);
	state.open_gl.msaa_enabled = false;
	ogl::initialize_framebuffer_for_province_indices(state, width, height);
}

// Renders the whole world map (flat projection, no labels) and writes it to path.
inline void screenshot(sys::state& state, map_mode::mode mode, int width, int height, std::string const& path) {
	init_offscreen_gl(state, width, height);
	state.user_settings.map_is_globe = sys::projection_mode::rectangle;
	state.user_settings.map_label = sys::map_label_mode::none;
	state.map_state.zoom = 1.f;
	state.map_state.pos = {glm::vec2(0.5f, 0.5f)};
	// the renderer moves the camera by (time since last frame) x velocity, and a mouse at (0,0) counts as edge
	// scrolling: minutes between two shots threw the second one off the world. Freeze the camera before each shot.
	state.user_settings.mouse_edge_scrolling = false;
	state.map_state.pos_velocity = glm::vec2(0.f);
	state.map_state.zoom_change = 0.f;
	state.map_state.last_update_time = std::chrono::steady_clock::now();
	state.x_size = width;
	state.y_size = height;
	// no player nation, so no fog of war: the observer sees every province (unsized, this vector is read out of bounds)
	state.map_state.visible_provinces.assign(state.world.province_size() + 1, true);
	map_mode::set_map_mode(state, mode);
	if(!shot_colors_file.empty()) {
		uint32_t province_size = state.world.province_size() + 1;
		uint32_t texture_size = province_size + 256 - province_size % 256;
		std::vector<uint32_t> prov_color(texture_size * 2, sys::pack_color(110, 110, 110));
		FILE* f = fopen(shot_colors_file.c_str(), "r");
		if(!f) { fprintf(stderr, "could not open %s\n", shot_colors_file.c_str()); exit(4); }
		int idx; unsigned rgb; int n = 0;
		while(fscanf(f, "%d,%x", &idx, &rgb) == 2) {
			auto i = province::to_map_id(dcon::province_id{dcon::province_id::value_base_t(idx)});
			prov_color[i] = prov_color[i + texture_size] = sys::pack_color(int32_t(rgb >> 16 & 0xFF), int32_t(rgb >> 8 & 0xFF), int32_t(rgb & 0xFF));
			++n;
		}
		fclose(f);
		state.map_state.set_province_color(prov_color, mode);
		printf("SHOTCOLORS %d provinces from %s\n", n, shot_colors_file.c_str());
	}

	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glViewport(0, 0, width, height);
	glClearColor(0.f, 0.f, 0.f, 1.f);
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
	state.map_state.render(state, uint32_t(width), uint32_t(height));
	glFinish();

	std::vector<uint8_t> pixels(size_t(width) * height * 3);
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glReadBuffer(GL_BACK);
	glPixelStorei(GL_PACK_ALIGNMENT, 1);
	glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
	stbi_flip_vertically_on_write(1);
	int ok = stbi_write_png(path.c_str(), width, height, 3, pixels.data(), width * 3);
	printf("SCREENSHOT %s -> %s (%dx%d) %s\n", ymd_of(state).c_str(), path.c_str(), width, height, ok ? "ok" : "FAILED");
	fflush(stdout);
}

} // namespace headless
#endif
