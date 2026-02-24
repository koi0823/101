import plotly.graph_objects as go
import random
import copy

# Tolerance for floating point comparisons to prevent microscopic misfits
# Increased to 1.0mm to handle real-world data imperfections/rounding errors
EPSILON = 1.0

class Item:
    def __init__(self, name, length, width, height, weight, 
                 color=None,
                 priority=1,        # 1=Most Inside (First loaded), higher numbers=Closer to door
                 type_id=None,      # Group ID for clustering
                 max_load_on_top=0.0, 
                 allow_stacking=True,
                 packaging_type=1): # 1: Pallet, 2: Crate
        
        self.name = name
        self.l = float(length)
        self.w = float(width)
        self.h = float(height)
        self.weight = float(weight)
        
        # Priority: Lower number = Loaded First = Deeper Inside Container
        self.priority = int(priority)
        
        self.type_id = type_id if type_id else f"{int(self.l)}x{int(self.w)}"
        self.max_load_on_top = float(max_load_on_top)
        self.allow_stacking = allow_stacking
        self.packaging_type = int(packaging_type)
        self.current_load_on_top = 0.0
        self.stack_layer = 1 # Tracks vertical position (1=Ground, 2=First Stack, etc.)
        
        # Derived props
        self.vol = self.l * self.w * self.h
        self.base_area = self.l * self.w
        
        # Consistent color based on name/type
        seed_key = type_id if type_id else name
        rd = random.Random(hash(seed_key))
        
        # Distinct Color Palettes for Packaging Types
        if self.packaging_type == 1: 
            # Pallet: Cool Tones (Blues, Cyans, Teals)
            r = rd.randint(50, 100)
            g = rd.randint(150, 220)
            b = rd.randint(200, 255)
        elif self.packaging_type == 2: 
            # Crate: Warm Tones (Oranges, Browns, Reds)
            r = rd.randint(200, 255)
            g = rd.randint(100, 160)
            b = rd.randint(50, 100)
        else:
            # Default/Other: Random
            r = rd.randint(100, 200)
            g = rd.randint(100, 200)
            b = rd.randint(100, 200)
            
        self.color = f'rgb({r}, {g}, {b})'
        
        self.x = 0
        self.y = 0
        self.z = 0
        self.rotation = 0 # 0: original, 1: rotated 90 deg on floor

    def get_dimension(self):
        # STRICT ROTATION LOGIC:
        # Rotation 0: Original L, W
        # Rotation 1: Swapped W, L (Rotated 90 deg on floor)
        # Height (H) is NEVER swapped, ensuring "No Upside Down" constraint.
        if self.rotation == 1:
            return self.w, self.l, self.h
        return self.l, self.w, self.h

class Container:
    def __init__(self, length, width, height, max_weight=28000, allow_stacking=True, min_gap=0.0):
        self.L = length
        self.W = width
        self.H = height
        self.max_weight = max_weight
        self.allow_stacking = allow_stacking
        # Note: min_gap argument is kept for compatibility but ignored in logic (Forced to 0)
        self.min_gap = 0.0 
        
        self.current_weight = 0.0
        self.items = []
        self.unpacked_items = []

    def can_support(self, item_below, item_above_candidate, candidate_x, candidate_y, candidate_z):
        # 1. Vertical Adjacency Check
        d_below = item_below.get_dimension()
        d_above = item_above_candidate.get_dimension()
        
        top_z_below = item_below.z + d_below[2]
        
        if abs(top_z_below - candidate_z) > EPSILON:
            return False

        # --- PACKAGING TYPE & STACKING RULES ---

        # Rule: Crate on Pallet: ❌ Forbidden
        if item_below.packaging_type == 1 and item_above_candidate.packaging_type == 2:
            return False 

        # Rule: Pallet on Crate: ✅ Allowed ONLY if Pallet is strictly smaller
        if item_below.packaging_type == 2 and item_above_candidate.packaging_type == 1:
             if d_above[0] >= d_below[0] - EPSILON or d_above[1] >= d_below[1] - EPSILON:
                 return False

        # Rule: Global Stacking Limit
        # 20ft Container (< 7000mm): Max 2 layers (Ground + 1 on top)
        # 40ft Container (>= 7000mm): Max 4 layers (High stacking allowed)
        max_layers = 2 if self.L < 7000 else 4
        
        if item_below.stack_layer >= max_layers:
            return False
        
        # General Stability Rule (Pyramid): Heavier on Bottom
        # MODIFIED: Allow 10% tolerance. E.g., 550kg can sit on 500kg.
        # This improves Vertical Balance (Top Weight).
        if item_above_candidate.weight > item_below.weight * 1.10:
            return False

        # --- END RULES ---

        # 3. Dimension Scanning (Standard Overhang Check)
        if d_above[0] > d_below[0] + EPSILON or d_above[1] > d_below[1] + EPSILON:
            return False

        # 4. Weight Limit Check (Load on bottom item)
        if item_below.current_load_on_top + item_above_candidate.weight > item_below.max_load_on_top:
            return False

        # 5. Surface Area Support Check (Strict No-Overlay Policy)
        # We increase strictness to 95% to prevent overhangs.
        overlap_x_start = max(item_below.x, candidate_x)
        overlap_x_end = min(item_below.x + d_below[0], candidate_x + d_above[0])
        
        overlap_y_start = max(item_below.y, candidate_y)
        overlap_y_end = min(item_below.y + d_below[1], candidate_y + d_above[1])
        
        overlap_w = max(0, overlap_x_end - overlap_x_start)
        overlap_l = max(0, overlap_y_end - overlap_y_start)
        
        support_area = overlap_w * overlap_l
        item_above_area = d_above[0] * d_above[1]
        
        if support_area < (item_above_area * 0.95):
            return False
            
        return True
        
    def get_all_valid_anchors(self, item, start_x_limit=0, end_x_limit=None, axis_priority='x', scoring_strategy='balanced'):
        """
        scoring_strategy: 'balanced' (Default, aggressively tries to balance weight) 
                          or 'density' (Tries to pack tightly to fit everything)
        """
        if end_x_limit is None: end_x_limit = self.L

        # --- STRICT NO GAP MODE ---
        gap = 0.0

        item_l, item_w, item_h = item.get_dimension()
        
        unique_x = {0, self.L, start_x_limit} 
        unique_y = {0, self.W}
        unique_z = {0} 
        
        if self.allow_stacking:
            for placed in self.items:
                if placed.allow_stacking:
                    unique_z.add(placed.z + placed.get_dimension()[2])

        # --- RIGHT WALL SNAPPING ---
        snap_y = self.W - item_w
        if snap_y >= -EPSILON:
            unique_y.add(snap_y)

        # --- DOOR WALL SNAPPING (Back-Right / Front-Right Corners) ---
        snap_x = self.L - item_l
        if snap_x >= -EPSILON:
            unique_x.add(snap_x)

        for placed in self.items:
            p_l, p_w, p_h = placed.get_dimension()
            # Standard Coordinates (Right/Front of neighbor)
            unique_x.add(placed.x)
            unique_x.add(placed.x + p_l) 
            
            unique_y.add(placed.y)
            unique_y.add(placed.y + p_w)
            
            # --- BACK-FILL / REVERSE ALIGNMENT ---
            if placed.x - item_l >= -EPSILON:
                    unique_x.add(placed.x - item_l)
            if placed.x + p_l - item_l >= -EPSILON:
                unique_x.add(placed.x + p_l - item_l)
            
            # --- LEFT-ALIGN / REVERSE ALIGNMENT ---
            if placed.y - item_w >= -EPSILON:
                unique_y.add(placed.y - item_w)
            if placed.y + p_w - item_w >= -EPSILON:
                unique_y.add(placed.y + p_w - item_w)

        local_anchors = []
        
        valid_x = [x for x in unique_x if x >= start_x_limit - EPSILON and x <= (end_x_limit - item_l) + EPSILON]
        valid_y = [y for y in unique_y if y + item_w <= self.W + EPSILON]
        valid_z = [z for z in unique_z if z + item_h <= self.H + EPSILON]

        for z in valid_z:
            for x in valid_x:
                for y in valid_y:
                    # Support Check
                    support_item = None
                    if z > 0:
                        supported = False
                        potential_supports = [p for p in self.items if abs((p.z + p.get_dimension()[2]) - z) < EPSILON]
                        for p in potential_supports:
                            if self.can_support(p, item, x, y, z):
                                support_item = p
                                supported = True
                                break 
                        if not supported: continue 
                            
                    # Collision Check
                    collision = False
                    safe_gap = 0.0 # Force 0 gap check
                    for other in self.items:
                        o_l, o_w, o_h = other.get_dimension()
                        # Strict AABB collision check
                        if (x < other.x + o_l + safe_gap - EPSILON and x + item_l + safe_gap > other.x + EPSILON and
                            y < other.y + o_w + safe_gap - EPSILON and y + item_w + safe_gap > other.y + EPSILON and
                            z < other.z + o_h - EPSILON and z + item_h > other.z + EPSILON):
                            collision = True
                            break
                    if collision: continue
                    
                    gap_metric = (end_x_limit - (x + item_l)) + (self.W - (y + item_w))
                    dist_to_left = y
                    dist_to_right = abs(self.W - (y + item_w))
                    min_wall_dist = min(dist_to_left, dist_to_right)

                    if scoring_strategy == 'density':
                        # DENSITY: Prioritize X, then Z, then Tightest Fit to ANY wall
                        sort_key = (x, z, min_wall_dist, gap_metric)
                        local_anchors.append((sort_key, (x, y, z), gap_metric, support_item))
                    else:
                        wall_bonus = 0
                        # Bonus for touching ANY side wall (Left OR Right)
                        if min_wall_dist < EPSILON: wall_bonus += 5000
                        # Bonus for Back Wall
                        if x < EPSILON: wall_bonus += 2000
                        
                        # GROUPING BONUS: Keep Crates with Crates, Pallets with Pallets
                        grouping_bonus = 0
                        type_bonus = 0
                        
                        for other in self.items:
                            dist = abs(other.x - x) + abs(other.y - y) + abs(other.z - z)
                            proximity_threshold = max(item_l, item_w, item_h) * 2
                            
                            if dist < proximity_threshold:
                                # High Bonus: Exact Type Match
                                if other.type_id == item.type_id:
                                    type_bonus += 20
                                # Med Bonus: Same Packaging Type
                                if other.packaging_type == item.packaging_type:
                                    grouping_bonus += 10
                        
                        adjacency_bonus = 0
                        
                        # STACKING BONUS LOGIC UPDATED
                        stacking_bonus = 0
                        perfect_match_stack = 0
                        
                        if z > 0:
                            # Base bonus for stacking (All must stack up)
                            stacking_bonus = 20000 
                            
                            # TWIN STACKING BONUS: If stacking on exact same item, prioritize heavily
                            if support_item and support_item.type_id == item.type_id:
                                perfect_match_stack = 50000

                        for other in self.items:
                            # Touch check
                            if (abs(x - (other.x + other.get_dimension()[0])) < EPSILON or abs((x + item_l) - other.x) < EPSILON or \
                                abs(y - (other.y + other.get_dimension()[1])) < EPSILON or abs((y + item_w) - other.y) < EPSILON) and \
                                abs(z - other.z) < other.get_dimension()[2]:
                                adjacency_bonus += 30 
                                break

                        # Sort Key: 10 Elements
                        sort_key = (x, z, -perfect_match_stack, -stacking_bonus, -wall_bonus, -grouping_bonus, -type_bonus, -adjacency_bonus, gap_metric, y)
                        local_anchors.append((sort_key, (x, y, z), gap_metric, support_item))
        
        local_anchors.sort(key=lambda item: item[0])
        return local_anchors

    def force_pack_item(self, unpacked_idx, x, y, z):
        """Forces an unpacked item into a specific exact x, y, z position."""
        if 0 <= unpacked_idx < len(self.unpacked_items):
            item = self.unpacked_items.pop(unpacked_idx)
            item.x = float(x)
            item.y = float(y)
            item.z = float(z)
            self.items.append(item)
            self.current_weight += item.weight
            return item
        return None

    def drop_unpacked_item(self, unpacked_idx, x, y):
        """Drops an unpacked item straight down at (x, y) until it hits the floor or another item."""
        if 0 <= unpacked_idx < len(self.unpacked_items):
            item = self.unpacked_items[unpacked_idx]
            l, w, h = item.get_dimension()
            
            # Find the highest Z collision footprint at this X, Y position
            drop_z = 0.0
            for placed in self.items:
                p_l, p_w, p_h = placed.get_dimension()
                
                # Check for X-Y coordinate footprint overlap
                if (x < placed.x + p_l - EPSILON and x + l > placed.x + EPSILON and
                    y < placed.y + p_w - EPSILON and y + w > placed.y + EPSILON):
                    
                    top_z = placed.z + p_h
                    if top_z > drop_z:
                        drop_z = top_z
                        
            # Use the force_pack_item method to move it directly to this calculated resting spot
            return self.force_pack_item(unpacked_idx, x, y, drop_z)
        return None

def calculate_balance_ratios(container):
    """Returns front_ratio, left_ratio"""
    if container.current_weight == 0: return 50.0, 50.0
    
    mid_L = container.L / 2
    mid_W = container.W / 2
    
    weight_nose, weight_left = 0.0, 0.0
    
    for item in container.items:
        # Longitudinal
        item_mid_x = item.x + (item.get_dimension()[0] / 2)
        if item_mid_x < mid_L: weight_nose += item.weight
        elif item_mid_x == mid_L: weight_nose += item.weight * 0.5
            
        # Lateral
        item_mid_y = item.y + (item.get_dimension()[1] / 2)
        if item_mid_y < mid_W: weight_left += item.weight
        elif item_mid_y == mid_W: weight_left += item.weight * 0.5

    ratio_nose = (weight_nose / container.current_weight) * 100
    ratio_left = (weight_left / container.current_weight) * 100
    
    return ratio_nose, ratio_left

def solve_packing(container_l, container_w, container_h, items_data, 
                  max_weight_kg=28000, 
                  allow_stacking=True, 
                  min_gap=0.0,
                  n_simulations=500,
                  max_lr_diff=1000,
                  max_fb_diff=1000):
    
    # 0. AUTO-DETECT CONTAINER SIZE
    is_40ft = container_l > 9000
    
    # 1. Scan and Build All Items List
    base_items_raw = []
    for d in items_data:
        for _ in range(int(d['qty'])):
            priority = int(d.get('priority', 1)) 
            packaging_type = int(d.get('packaging_type', 1))
            max_load = d.get('max_load', None)
            if max_load is None: max_load = d['weight'] 
            else: max_load = float(max_load)

            base_items_raw.append(
                Item(d['name'], d['l'], d['w'], d['h'], d['weight'], 
                     priority=priority, 
                     type_id=d.get('type_id', None),
                     max_load_on_top=max_load,
                     allow_stacking=allow_stacking,
                     packaging_type=packaging_type)
            )
            
    total_batch_weight = sum(item.weight for item in base_items_raw)
    
    # 2. DECIDE STRATEGY BASED ON CONTAINER LENGTH
    part_a, part_b, part_c = [], [], []
    
    if is_40ft:
        target_a = 0.20 * total_batch_weight 
        must_go_a, can_go_b, others = [], [], []
        
        for item in base_items_raw:
            max_d = max(item.l, item.w)
            if max_d > 9000: must_go_a.append(item)
            elif max_d >= 3000: can_go_b.append(item)
            else: others.append(item)
        
        part_a.extend(must_go_a)
        current_a_weight = sum(i.weight for i in part_a)
        others.sort(key=lambda x: (x.h, x.weight), reverse=True)
        remaining_others = []
        for item in others:
            if current_a_weight < target_a:
                part_a.append(item)
                current_a_weight += item.weight
            else:
                remaining_others.append(item)
        
        part_b.extend(can_go_b)
        remaining_others.sort(key=lambda x: (x.type_id, x.weight, x.h), reverse=True)
        remaining_for_c = []
        current_b_weight = sum(i.weight for i in part_b)
        target_b_fill = total_batch_weight * 0.60 
        
        for item in remaining_others:
            if current_b_weight < target_b_fill:
                part_b.append(item)
                current_b_weight += item.weight
            else:
                remaining_for_c.append(item)
                
        part_c.extend(remaining_for_c)
    else:
        target_a = 0.42 * total_batch_weight
        pool = sorted(base_items_raw, key=lambda x: (x.h, x.weight), reverse=True)
        current_a_weight = 0.0
        for item in pool:
            if current_a_weight < target_a:
                part_a.append(item)
                current_a_weight += item.weight
            else:
                part_b.append(item)

        max_iterations = 2000 
        min_a_ratio = 40.0
        max_a_ratio = 45.0
        for _ in range(max_iterations):
            wt_a = sum(i.weight for i in part_a)
            ratio_a = (wt_a / total_batch_weight * 100) if total_batch_weight > 0 else 0
            if min_a_ratio <= ratio_a <= max_a_ratio: break 
            
            if ratio_a > max_a_ratio:
                candidates = [i for i in part_a if i.l < 3000]
                if not candidates: break
                candidates.sort(key=lambda x: (x.h, -x.weight))
                item_to_move = candidates[0]
                part_a.remove(item_to_move)
                part_b.append(item_to_move)
            elif ratio_a < min_a_ratio:
                if not part_b: break
                part_b.sort(key=lambda x: (-x.h, -x.weight))
                item_to_move = part_b[0]
                part_b.remove(item_to_move)
                part_a.append(item_to_move)

    # 3. Final Sort
    def sort_key_smart_vertical(x):
        max_dim = max(x.l, x.w)
        is_super_long = 2 if max_dim >= 6000 else (1 if max_dim >= 3000 else 0)
        user_priority = -x.priority
        h_bin = int(x.h / 100) 
        return (is_super_long, user_priority, h_bin, x.weight, x.h)

    part_a.sort(key=sort_key_smart_vertical, reverse=True)
    part_b.sort(key=sort_key_smart_vertical, reverse=True)
    if is_40ft: part_c.sort(key=sort_key_smart_vertical, reverse=True)
    
    final_load_order = part_a + part_b + part_c if is_40ft else part_a + part_b

    # 4. Helper Function
    def pack_into_container(container, items_pool, strategy):
        if strategy == "Spot_Centric_Fit":
             while len(items_pool) > 0:
                global_best_move = None
                global_best_metric = (float('inf'),) * 12 
                for idx, item in enumerate(items_pool):
                    if container.current_weight + item.weight > container.max_weight: continue
                    if item.l > container.W: rotations = [0]
                    elif item.packaging_type == 1: rotations = [1, 0]
                    else: rotations = [0, 1]
                    
                    for rot in rotations:
                        item.rotation = rot
                        anchors = container.get_all_valid_anchors(item, scoring_strategy='balanced')
                        if anchors:
                            best_a = anchors[0]
                            if best_a[0] < global_best_metric:
                                global_best_metric = best_a[0]
                                global_best_move = (idx, rot, best_a[1], best_a[3])
                
                if global_best_move:
                    idx, rot, (x,y,z), support = global_best_move
                    winner = items_pool.pop(idx)
                    winner.rotation = rot
                    winner.x, winner.y, winner.z = x, y, z
                    if support:
                        support.current_load_on_top += winner.weight
                        winner.stack_layer = support.stack_layer + 1
                    else:
                        winner.stack_layer = 1
                    container.items.append(winner)
                    container.current_weight += winner.weight
                else:
                    container.unpacked_items.extend(items_pool)
                    break
                    
        elif strategy == "Density_First_Fit":
             while len(items_pool) > 0:
                found_fit = False
                for idx, item in enumerate(items_pool):
                    if container.current_weight + item.weight > container.max_weight: continue
                    if item.l > container.W: rotations = [0]
                    elif item.packaging_type == 1: rotations = [1, 0]
                    else: rotations = [0, 1]

                    best_anchor, best_rot = None, 0
                    for rot in rotations:
                        item.rotation = rot
                        anchors = container.get_all_valid_anchors(item, scoring_strategy='density')
                        if anchors:
                            if best_anchor is None or anchors[0][0] < best_anchor[0]:
                                best_anchor = anchors[0]
                                best_rot = rot
                    if best_anchor:
                        winner = items_pool.pop(idx)
                        winner.rotation, winner.x, winner.y, winner.z = best_rot, best_anchor[1][0], best_anchor[1][1], best_anchor[1][2]
                        support = best_anchor[3]
                        if support:
                            support.current_load_on_top += winner.weight
                            winner.stack_layer = support.stack_layer + 1
                        else:
                            winner.stack_layer = 1
                        container.items.append(winner)
                        container.current_weight += winner.weight
                        found_fit = True
                        break 
                if not found_fit:
                    container.unpacked_items.extend(items_pool)
                    break

    # 5. PACKING EXECUTION
    best_container = None
    best_score = float('inf')
    packing_strategies = ["Spot_Centric_Fit", "Density_First_Fit"]
    
    for strat in packing_strategies:
        initial_stacking = True if not is_40ft else False
        container = Container(container_l, container_w, container_h, max_weight=max_weight_kg, allow_stacking=initial_stacking, min_gap=min_gap)
        current_pool = copy.deepcopy(final_load_order)
        pack_into_container(container, current_pool, strat)
        
        if len(container.unpacked_items) > 0:
            container.allow_stacking = True
            leftovers = container.unpacked_items
            container.unpacked_items = [] 
            leftovers.sort(key=lambda x: (x.weight, x.base_area), reverse=True)
            pack_into_container(container, leftovers, strat)

        score = len(container.unpacked_items) * 10000
        ratio_nose, _ = calculate_balance_ratios(container)
        score += abs(ratio_nose - 50) * 10
            
        if score < best_score:
            best_score = score
            best_container = container
            
    # SET INITIAL SLIDER COORDINATES FOR UNPACKED ITEMS
    if best_container:
        mid_L = best_container.L / 2
        mid_W = best_container.W / 2
        mid_H = best_container.H / 2
        for item in best_container.unpacked_items:
            l, w, h = item.get_dimension()
            item.x = mid_L - (l / 2)
            item.y = mid_W - (w / 2)
            item.z = mid_H - (h / 2)
            
    return best_container

def get_container_stats(container):
    total_vol = container.L * container.W * container.H
    used_vol = sum(i.vol for i in container.items)
    total_weight = sum(i.weight for i in container.items)
    
    w_nose, w_door = 0.0, 0.0
    w_left, w_right = 0.0, 0.0
    w_bottom, w_top = 0.0, 0.0
    mid_L, mid_W, mid_H = container.L/2, container.W/2, container.H/2
    
    moment_x = 0.0
    moment_y = 0.0
    moment_z = 0.0
    
    for item in container.items:
        cx = item.x + item.get_dimension()[0]/2
        cy = item.y + item.get_dimension()[1]/2
        cz = item.z + item.get_dimension()[2]/2
        moment_x += cx * item.weight
        moment_y += cy * item.weight
        moment_z += cz * item.weight
        
        if cx < mid_L: w_nose += item.weight
        else: w_door += item.weight
        if cy < mid_W: w_left += item.weight
        else: w_right += item.weight
        if cz < mid_H: w_bottom += item.weight
        else: w_top += item.weight

    if total_weight > 0:
        cog_x, cog_y, cog_z = moment_x/total_weight, moment_y/total_weight, moment_z/total_weight
    else:
        cog_x, cog_y, cog_z = mid_L, mid_W, mid_H

    # Calculate ratios safe for division
    ratio_len = (w_nose / total_weight * 100) if total_weight > 0 else 50.0
    ratio_width = (w_left / total_weight * 100) if total_weight > 0 else 50.0
    ratio_height = (w_bottom / total_weight * 100) if total_weight > 0 else 50.0

    return {
        "packed_count": len(container.items),
        "unpacked_count": len(container.unpacked_items),
        "weight_total": total_weight,
        "weight_utilization": (total_weight / container.max_weight * 100) if container.max_weight > 0 else 0,
        "volume_utilization": (used_vol / total_vol) * 100,
        "weight_nose": w_nose, "weight_door": w_door,
        "weight_left": w_left, "weight_right": w_right,
        "weight_bottom": w_bottom, "weight_top": w_top,
        "balance_ratio": ratio_len,
        "balance_ratio_len": ratio_len,
        "balance_ratio_width": ratio_width,
        "balance_ratio_height": ratio_height,
        "cog_x": cog_x, "cog_y": cog_y, "cog_z": cog_z
    }

def visualize_container(container, highlight_name=None):
    fig = go.Figure()
    L, W, H = container.L, container.W, container.H
    
    # 1. Container Wireframe
    cage_lines = [
        ([0, L], [0, 0], [0, 0]), ([0, L], [W, W], [0, 0]), ([0, L], [0, 0], [H, H]), ([0, L], [W, W], [H, H]),
        ([0, 0], [0, W], [0, 0]), ([L, L], [0, W], [0, 0]), ([0, 0], [0, W], [H, H]), ([L, L], [0, W], [H, H]),
        ([0, 0], [0, 0], [0, H]), ([L, L], [0, 0], [0, H]), ([0, 0], [W, W], [0, H]), ([L, L], [W, W], [0, H])
    ]
    for lx, ly, lz in cage_lines:
        fig.add_trace(go.Scatter3d(x=lx, y=ly, z=lz, mode='lines', line=dict(color='white', width=4), showlegend=False, hoverinfo='skip'))

    # 2. Add Packed Items
    for i, item in enumerate(container.items):
        x, y, z = item.x, item.y, item.z
        l, w, h = item.get_dimension()
        
        vx = [x, x+l, x+l, x, x, x+l, x+l, x]
        vy = [y, y, y+w, y+w, y, y, y+w, y+w]
        vz = [z, z, z, z, z+h, z+h, z+h, z+h]
        
        i_idx = [0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 3, 3]
        j_idx = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 0, 4]
        k_idx = [2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 4, 7]
        
        type_str = "Pallet" if item.packaging_type == 1 else "Crate"
        
        # Dim non-highlighted packed items slightly if a highlight is active
        opacity = 1.0
        if highlight_name and highlight_name != item.name:
            opacity = 0.2
            
        fig.add_trace(go.Mesh3d(
            x=vx, y=vy, z=vz,
            i=i_idx, j=j_idx, k=k_idx,
            color=item.color,
            opacity=opacity,
            flatshading=True,
            name=item.name,
            customdata=[f"P_{i}"] * len(vx),
            text=f"Priority: {item.priority}<br>{item.name}<br>Type: {type_str}<br>Pos: {x:.0f},{y:.0f},{z:.0f}"
        ))
        
        edges = [
            ([x, x+l], [y, y], [z, z]), ([x, x+l], [y+w, y+w], [z, z]), 
            ([x, x+l], [y, y], [z+h, z+h]), ([x, x+l], [y+w, y+w], [z+h, z+h]),
            ([x, x], [y, y+w], [z, z]), ([x+l, x+l], [y, y+w], [z, z]),
            ([x, x], [y, y+w], [z+h, z+h]), ([x+l, x+l], [y, y+w], [z+h, z+h]),
            ([x, x], [y, y], [z, z+h]), ([x+l, x+l], [y, y], [z, z+h]),
            ([x, x], [y+w, y+w], [z, z+h]), ([x+l, x+l], [y+w, y+w], [z, z+h])
        ]
        for ex, ey, ez in edges:
            fig.add_trace(go.Scatter3d(x=ex, y=ey, z=ez, mode='lines', line=dict(color='black', width=2), showlegend=False, hoverinfo='skip'))

    # 3. Add Unpacked Items (Ghost items now dynamically follow their x,y,z)
    for i, item in enumerate(container.unpacked_items):
        l, w, h = item.get_dimension()
        x, y, z = item.x, item.y, item.z
        
        vx = [x, x+l, x+l, x, x, x+l, x+l, x]
        vy = [y, y, y+w, y+w, y, y, y+w, y+w]
        vz = [z, z, z, z, z+h, z+h, z+h, z+h]
        
        i_idx = [0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 3, 3]
        j_idx = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 0, 4]
        k_idx = [2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 4, 7]
        
        # Ghostly Red effect
        opacity = 0.8 if highlight_name == item.name else 0.4
            
        fig.add_trace(go.Mesh3d(
            x=vx, y=vy, z=vz,
            i=i_idx, j=j_idx, k=k_idx,
            color='rgba(239, 68, 68, 0.5)', 
            opacity=opacity,
            flatshading=True,
            name=f"UNPACKED_{i}",
            customdata=[f"U_{i}"] * len(vx),
            text=f"⚠️ UNPACKED<br>{item.name}<br>Dim: {l:.0f}x{w:.0f}x{h:.0f}"
        ))
        
        edges = [
            ([x, x+l], [y, y], [z, z]), ([x, x+l], [y+w, y+w], [z, z]), 
            ([x, x+l], [y, y], [z+h, z+h]), ([x, x+l], [y+w, y+w], [z+h, z+h]),
            ([x, x], [y, y+w], [z, z]), ([x+l, x+l], [y, y+w], [z, z]),
            ([x, x], [y, y+w], [z+h, z+h]), ([x+l, x+l], [y, y+w], [z+h, z+h]),
            ([x, x], [y, y], [z, z+h]), ([x+l, x+l], [y, y], [z, z+h]),
            ([x, x], [y+w, y+w], [z, z+h]), ([x+l, x+l], [y+w, y+w], [z, z+h])
        ]
        for ex, ey, ez in edges:
            fig.add_trace(go.Scatter3d(x=ex, y=ey, z=ez, mode='lines', line=dict(color='red', width=3, dash='dash'), showlegend=False, hoverinfo='skip'))

    # 4. CoG Marker
    stats = get_container_stats(container)
    cog_x, cog_y, cog_z = stats['cog_x'], stats['cog_y'], stats['cog_z']
    fig.add_trace(go.Scatter3d(
        x=[cog_x], y=[cog_y], z=[cog_z],
        mode='markers', marker=dict(size=12, color='blue', symbol='circle'),
        name='Center of Gravity'
    ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(range=[0, L], title="Length", backgroundcolor="#0f172a"),
            yaxis=dict(range=[0, W], title="Width", backgroundcolor="#0f172a"),
            zaxis=dict(range=[0, H], title="Height", backgroundcolor="#0f172a"),
            aspectmode='data'
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, b=0, t=0)
    )
    return fig