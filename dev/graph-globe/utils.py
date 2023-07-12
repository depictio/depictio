import numpy as np
import random
import hashlib

class Graph:
    def __init__(self, num_nodes, location):
        self.num_nodes = num_nodes
        self.location = location
        self.nodes = []
        self.edges = []
        self.set_seed()
        self.build_graph()

    def set_seed(self):
        # Generate a hash of the location string
        hasher = hashlib.sha1()
        hasher.update(self.location.encode('utf-8'))
        hash_val = int(hasher.hexdigest(), 16)

        # Reduce the hash value modulo 2^32 to create a valid seed
        seed = hash_val % (2**32)
        print(seed)

        # Use the seed to seed the random number generator
        random.seed(seed)
        np.random.seed(seed)


    def build_graph(self):
        for i in range(self.num_nodes):
            node_id = f"{self.location}_species{i + 1}"
            node_label = f"Species {i + 1}"
            node_href = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text=Species{i + 1}"
            num_edges = random.randint(1, 3) if i < self.num_nodes - 2 else random.randint(8, 12)
            self.nodes.append({"data": {"id": node_id, "label": node_label, "href": node_href, "num_edges": num_edges}})

        num_edges = 0

        for source_node in self.nodes:
            source_node_id = source_node["data"]["id"]
            available_targets = [node for node in self.nodes if node["data"]["id"] != source_node_id and node["data"]["num_edges"] > 0]
            num_source_edges = source_node["data"]["num_edges"]

            while num_source_edges > 0 and len(available_targets) > 0:
                num_target_edges = min(num_source_edges, len(available_targets))
                selected_targets = random.sample(available_targets, num_target_edges)
                
                for target_node in selected_targets:
                    target_node_id = target_node["data"]["id"]
                    edge_id = f"{self.location}_edge{num_edges + 1}"
                    intensity = random.uniform(0.1, 1.0)
                    edge_image = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text={source_node_id}-{target_node_id}"
                    self.edges.append({"data": {"id": edge_id, "source": source_node_id, "target": target_node_id, "image": edge_image, "intensity": intensity}})
                    num_edges += 1
                    num_source_edges -= 1
                
                available_targets = [node for node in self.nodes if node["data"]["id"] != source_node_id and node["data"]["num_edges"] > 0]
            source_node["data"]["num_edges"] = num_source_edges

# location1 = Graph(20, "location1")
# location2 = Graph(20, "location2")
