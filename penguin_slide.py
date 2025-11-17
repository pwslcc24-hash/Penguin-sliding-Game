import math
import random
import sys
from dataclasses import dataclass
from typing import List, Tuple

import pygame

# -------------------------------
# Game wide configuration values
# -------------------------------
WIDTH, HEIGHT = 960, 540
FPS = 60
SKY_COLOR = (125, 195, 255)
GROUND_COLOR = (30, 150, 95)
GROUND_SHADOW = (20, 110, 70)
PENGUIN_COLOR = (25, 25, 35)
PENGUIN_BELLY = (240, 240, 250)

# Physics tuning
GRAVITY = 1800.0           # pixels / s^2
BASE_SCROLL_SPEED = 260.0  # how fast the world moves to the left
SLIDE_GRAVITY_MULT = 1.65  # extra downhill pull while holding space
GROUND_DRAG = 0.35
AIR_DRAG = 0.04
RELEASE_POP = 220.0        # vertical kick when taking off
PERFECT_CHARGE_RATE = 1.6
PERFECT_DECAY = 0.4
PERFECT_DOWNHILL_SLOPE = -0.3
PERFECT_RELEASE_SLOPE = 0.08
PERFECT_BOOST = 180.0
MIN_LAUNCH_SPEED = 140.0


class Terrain:
    """Layered sine waves to create rolling hills."""

    def __init__(self, base_height: float = HEIGHT * 0.65, seed: int | None = None):
        rng = random.Random(seed)
        self.base_height = base_height
        self.waves: List[Tuple[float, float, float]] = []
        for _ in range(4):
            amplitude = rng.uniform(40, 120)
            wavelength = rng.uniform(280, 520)
            phase = rng.uniform(0, math.tau)
            self.waves.append((amplitude, wavelength, phase))

    def height(self, x: float) -> float:
        y = self.base_height
        for amplitude, wavelength, phase in self.waves:
            y += amplitude * math.sin((x / wavelength) * math.tau + phase)
        return y

    def slope(self, x: float) -> float:
        dy = 0.0
        for amplitude, wavelength, phase in self.waves:
            dy += amplitude * math.cos((x / wavelength) * math.tau + phase) * (math.tau / wavelength)
        return dy


@dataclass
class Penguin:
    terrain: Terrain
    world_x: float = 120.0
    y: float = 0.0
    vx: float = BASE_SCROLL_SPEED
    vy: float = 0.0
    speed_along_ground: float = BASE_SCROLL_SPEED
    on_ground: bool = True
    perfect_charge: float = 0.0

    def __post_init__(self) -> None:
        self.y = self.terrain.height(self.world_x)
        self.prev_slope = self.terrain.slope(self.world_x)
        self.was_holding = False

    def update(self, dt: float, holding_space: bool) -> None:
        if self.on_ground:
            self._update_ground(dt, holding_space)
        else:
            self._update_air(dt, holding_space)
        self.was_holding = holding_space
        self.prev_slope = self.terrain.slope(self.world_x)

    def _update_ground(self, dt: float, holding_space: bool) -> None:
        ground_y = self.terrain.height(self.world_x)
        slope = self.terrain.slope(self.world_x)
        angle = math.atan(slope)
        tangent_x = math.cos(angle)
        tangent_y = math.sin(angle)

        # Gravity projected onto the slope controls how the penguin accelerates
        gravity_along = GRAVITY * math.sin(angle)
        accel = gravity_along
        if holding_space:
            accel *= SLIDE_GRAVITY_MULT
        self.speed_along_ground += accel * dt

        # Sliding uphill naturally slows the penguin down
        if slope > 0:
            self.speed_along_ground -= slope * 120.0 * dt

        # Small amount of ground drag to prevent runaway speeds
        self.speed_along_ground -= self.speed_along_ground * GROUND_DRAG * dt
        self.speed_along_ground = max(20.0, self.speed_along_ground)

        self.vx = self.speed_along_ground * tangent_x
        self.vy = self.speed_along_ground * tangent_y
        self.world_x += self.vx * dt
        self.y = ground_y

        # Charge up the perfect slide bonus while holding space on steep downhills
        if holding_space and slope < PERFECT_DOWNHILL_SLOPE:
            self.perfect_charge = min(1.0, self.perfect_charge + PERFECT_CHARGE_RATE * dt)
        else:
            self.perfect_charge = max(0.0, self.perfect_charge - PERFECT_DECAY * dt)

        # Releasing space right at the valley bottom grants a horizontal boost
        if (not holding_space and self.was_holding and self.perfect_charge > 0.15
                and abs(slope) <= PERFECT_RELEASE_SLOPE):
            self.speed_along_ground += PERFECT_BOOST * self.perfect_charge
            self.perfect_charge = 0.0
            self._launch_from_slope(slope)
            return

        # If the player lets go near the bottom the penguin launches into the air
        if not holding_space and slope > -0.02 and self.speed_along_ground > MIN_LAUNCH_SPEED:
            self._launch_from_slope(slope)
            return

    def _update_air(self, dt: float, holding_space: bool) -> None:
        self.vy += GRAVITY * dt
        # Holding space in the air makes the penguin dive faster
        if holding_space:
            self.vy += GRAVITY * 0.3 * dt
        # Gentle air drag keeps crazy speeds in check
        self.vx -= self.vx * AIR_DRAG * dt

        self.world_x += self.vx * dt
        self.y += self.vy * dt

        ground_y = self.terrain.height(self.world_x)
        if self.y >= ground_y and self.vy >= 0:
            slope = self.terrain.slope(self.world_x)
            if holding_space:
                # Dive straight into the hillside and resume sliding
                self.y = ground_y
                self._stick_to_ground(slope)
            else:
                # Touch down and immediately release back into the air by following the slope
                self.y = ground_y
                self._stick_to_ground(slope)
                self._launch_from_slope(slope)

    def _launch_from_slope(self, slope: float) -> None:
        """Convert the ground speed into world velocity for takeoff."""
        angle = math.atan(slope)
        tangent_x = math.cos(angle)
        tangent_y = math.sin(angle)
        speed = max(self.speed_along_ground, MIN_LAUNCH_SPEED)
        self.vx = speed * tangent_x
        self.vy = speed * tangent_y - RELEASE_POP
        self.on_ground = False

    def _stick_to_ground(self, slope: float) -> None:
        angle = math.atan(slope)
        tangent_x = math.cos(angle)
        tangent_y = math.sin(angle)
        speed = math.hypot(self.vx, self.vy)
        self.speed_along_ground = max(20.0, speed)
        self.vx = self.speed_along_ground * tangent_x
        self.vy = self.speed_along_ground * tangent_y
        self.on_ground = True

    @property
    def screen_x(self) -> float:
        return WIDTH * 0.35


def draw_terrain(surface: pygame.Surface, terrain: Terrain, camera_x: float) -> None:
    step = 6
    points: List[Tuple[float, float]] = []
    for screen_x in range(-step, WIDTH + step, step):
        world_x = camera_x + screen_x
        points.append((screen_x, terrain.height(world_x)))
    points.append((WIDTH, HEIGHT))
    points.append((0, HEIGHT))
    pygame.draw.polygon(surface, GROUND_SHADOW, points)
    pygame.draw.lines(surface, GROUND_COLOR, False, points[:-2], 4)
    pygame.draw.polygon(surface, GROUND_COLOR, points)


def draw_penguin(surface: pygame.Surface, penguin: Penguin) -> None:
    x = penguin.screen_x
    y = penguin.y
    body = pygame.Rect(0, 0, 60, 70)
    body.center = (x, y - 5)
    pygame.draw.ellipse(surface, PENGUIN_COLOR, body)
    belly = body.inflate(-18, -20)
    pygame.draw.ellipse(surface, PENGUIN_BELLY, belly)
    eye_center = (int(x + 12), int(y - 18))
    pygame.draw.circle(surface, (255, 255, 255), eye_center, 7)
    pygame.draw.circle(surface, (0, 0, 0), eye_center, 3)
    if penguin.perfect_charge > 0.25:
        pygame.draw.circle(surface, (255, 255, 255), (int(x), int(y)), 46, 2)


def draw_hud(surface: pygame.Surface, font: pygame.font.Font, penguin: Penguin) -> None:
    state = "SLIDE" if penguin.on_ground else "AIR"
    speed = math.hypot(penguin.vx, penguin.vy)
    text = font.render(f"Speed: {int(speed)}  State: {state}", True, (10, 10, 10))
    surface.blit(text, (16, 16))
    perfect = font.render(f"Perfect: {int(penguin.perfect_charge * 100)}%", True, (10, 10, 10))
    surface.blit(perfect, (16, 46))
    hint = font.render("Hold SPACE to dive, release in valleys!", True, (10, 10, 10))
    surface.blit(hint, (16, HEIGHT - 36))


def handle_events() -> tuple[bool, bool]:
    holding_space = False
    quit_game = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            quit_game = True
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            quit_game = True
    keys = pygame.key.get_pressed()
    holding_space = keys[pygame.K_SPACE]
    return holding_space, quit_game


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Tiny Wings Penguin")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 22)

    terrain = Terrain()
    penguin = Penguin(terrain)
    camera_x = penguin.world_x - penguin.screen_x

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        holding_space, quit_game = handle_events()
        if quit_game:
            break

        penguin.update(dt, holding_space)
        camera_x = penguin.world_x - penguin.screen_x

        screen.fill(SKY_COLOR)
        draw_terrain(screen, terrain, camera_x)
        draw_penguin(screen, penguin)
        draw_hud(screen, font, penguin)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
