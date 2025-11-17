import math
import random
import sys
from dataclasses import dataclass
from typing import Tuple

import pygame

# ----------------------------
# Terrain generation settings
# ----------------------------
WIDTH, HEIGHT = 800, 600
FPS = 60
GRAVITY = 900.0          # pixels per second^2
SLIDE_FORCE = 1200.0     # how strongly slopes affect the slide speed
UPHILL_PENALTY = 8.0     # slows the penguin down when climbing while diving
SLIDE_FRICTION = 0.8     # resistive force while sliding
PERFECT_DOWN_SLOPE = -0.45  # slope threshold for charging the speed bonus
PERFECT_RELEASE_SLOPE = 0.12
PERFECT_CHARGE_RATE = 0.7
PERFECT_BONUS = 0.9
LAUNCH_POP = 140.0       # added vertical kick when releasing from the ground
AIR_DRAG = 0.15
SKY_COLOR = (120, 190, 255)
GROUND_COLOR = (30, 160, 90)
HILL_SHADOW_COLOR = (10, 110, 60)


class Terrain:
    """Generates an infinite scrolling set of hills using layered sine waves."""

    def __init__(self, base_height=400, seed=7):
        self.base_height = base_height
        rng = random.Random(seed)
        self.waves = []
        for _ in range(5):
            amplitude = rng.uniform(40, 120)
            wavelength = rng.uniform(220, 520)
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
    world_x: float = 80.0
    y: float = 0.0
    vx: float = 120.0
    vy: float = 0.0
    is_sliding: bool = True
    perfect_charge: float = 0.0

    def __post_init__(self):
        self.y = self.terrain.height(self.world_x)
        self.was_holding = False
        self.perfect_timer = 0.0

    def launch_from_slope(self, slope: float):
        """Converts the sliding speed into an aerial arc."""
        angle = math.atan(slope)
        speed = max(self.vx, 60.0)
        bonus = 1.0
        if self.perfect_charge > 0.5 and abs(slope) < PERFECT_RELEASE_SLOPE:
            bonus += self.perfect_charge * PERFECT_BONUS
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        self.vx = speed * direction_x * bonus
        # Give a little upward pop so releasing on flat ground still lifts off
        self.vy = (speed * direction_y - LAUNCH_POP) * bonus
        self.is_sliding = False
        self.perfect_charge = 0.0
        self.perfect_timer = 0.0

    def update(self, dt: float, holding_space: bool):
        if self.is_sliding:
            self._update_sliding(dt, holding_space)
        else:
            self._update_airborne(dt, holding_space)
        self.was_holding = holding_space

    def _update_sliding(self, dt: float, holding_space: bool):
        ground_y = self.terrain.height(self.world_x)
        slope = self.terrain.slope(self.world_x)
        self.y = ground_y
        if holding_space:
            # Downhill acceleration rewards pressing space on steep declines
            downhill_push = -slope * SLIDE_FORCE
            self.vx += downhill_push * dt
            if slope > 0:
                # Penalty for staying glued to the uphill part of a hill
                self.vx -= slope * UPHILL_PENALTY
            self.vx -= self.vx * SLIDE_FRICTION * dt
            self.vx = max(self.vx, 20.0)
            self.world_x += self.vx * dt

            if slope < PERFECT_DOWN_SLOPE:
                # Charge up the "perfect" boost while on a steep downhill
                self.perfect_charge = min(1.0, self.perfect_charge + PERFECT_CHARGE_RATE * dt)
                self.perfect_timer = 0.0
            else:
                self.perfect_timer += dt
                if self.perfect_timer > 0.4:
                    self.perfect_charge = max(0.0, self.perfect_charge - dt)
        else:
            # Space released while sliding -> jump!
            self.launch_from_slope(slope)

    def _update_airborne(self, dt: float, holding_space: bool):
        # Simple airborne physics: gravity + gentle drag
        self.vy += GRAVITY * dt
        self.vx -= self.vx * AIR_DRAG * dt
        self.world_x += self.vx * dt
        self.y += self.vy * dt

        ground_y = self.terrain.height(self.world_x)
        if self.y >= ground_y:
            slope = self.terrain.slope(self.world_x)
            if holding_space:
                # Dive back to the surface and start sliding immediately
                self.y = ground_y
                self.vy = 0.0
                self.is_sliding = True
            else:
                # Bounce off the ground into another glide when space isn't held
                self.y = ground_y - 2
                # reuse release logic without granting extra bonus
                self.vx = max(self.vx, 60.0)
                angle = math.atan(slope)
                speed = max(60.0, math.hypot(self.vx, self.vy)) * 0.95
                self.vx = speed * math.cos(angle)
                self.vy = speed * math.sin(angle) - LAUNCH_POP * 0.6
                self.is_sliding = False

    @property
    def speed(self) -> float:
        if self.is_sliding:
            return abs(self.vx)
        return math.hypot(self.vx, self.vy)


def draw_terrain(surface: pygame.Surface, terrain: Terrain, camera_x: float):
    """Builds a polygon that matches the sampled hill heights for the screen."""
    points = []
    step = 8
    for screen_x in range(-step, WIDTH + step, step):
        world_x = camera_x + screen_x
        y = terrain.height(world_x)
        points.append((screen_x, y))
    # close polygon to bottom of the screen
    points.append((WIDTH, HEIGHT))
    points.append((0, HEIGHT))
    pygame.draw.polygon(surface, HILL_SHADOW_COLOR, points)
    pygame.draw.polygon(surface, GROUND_COLOR, points)


def draw_penguin(surface: pygame.Surface, screen_pos: Tuple[float, float], perfect_charge: float):
    """Renders a simple cartoon penguin plus a glow when the slide is perfect."""
    x, y = screen_pos
    body_rect = pygame.Rect(0, 0, 60, 70)
    body_rect.center = (x, y)
    pygame.draw.ellipse(surface, (20, 20, 30), body_rect)

    belly_rect = body_rect.inflate(-20, -15)
    pygame.draw.ellipse(surface, (230, 240, 255), belly_rect)

    beak = [(x + 30, y), (x + 45, y - 6), (x + 45, y + 6)]
    pygame.draw.polygon(surface, (250, 190, 20), beak)

    eye_center = (x + 10, y - 15)
    pygame.draw.circle(surface, (255, 255, 255), eye_center, 7)
    pygame.draw.circle(surface, (0, 0, 0), eye_center, 3)

    if perfect_charge > 0.3:
        pygame.draw.circle(surface, (255, 255, 255, 80), (int(x), int(y)), 40, 2)
        text = f"Perfect {int(perfect_charge * 100)}%"
        return text
    return ""


def draw_hud(surface: pygame.Surface, font: pygame.font.Font, speed: float):
    speed_text = font.render(f"Speed: {int(speed)} px/s", True, (20, 20, 20))
    surface.blit(speed_text, (20, 20))


def handle_events() -> tuple[bool, bool]:
    """Reads Pygame's event queue and reports space/quit state."""
    holding_space = False
    quit_game = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            quit_game = True
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                quit_game = True
    keys = pygame.key.get_pressed()
    holding_space = keys[pygame.K_SPACE]
    return holding_space, quit_game


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Penguin Hill Slide")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 24)

    terrain = Terrain()
    penguin = Penguin(terrain=terrain)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        holding_space, quit_game = handle_events()
        if quit_game:
            running = False
            continue

        penguin.update(dt, holding_space)
        camera_x = penguin.world_x - WIDTH * 0.3

        screen.fill(SKY_COLOR)
        draw_terrain(screen, terrain, camera_x)
        penguin_screen_pos = (WIDTH * 0.3, penguin.y)
        perfect_text = draw_penguin(screen, penguin_screen_pos, penguin.perfect_charge)
        draw_hud(screen, font, penguin.speed)
        if perfect_text:
            text_surface = font.render(perfect_text, True, (255, 255, 255))
            screen.blit(text_surface, (WIDTH * 0.35, 40))

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
