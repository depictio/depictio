import numpy as np
import random
import hashlib
from datetime import datetime, timedelta


def generate_metadata(locations):
    metadata = {}
    for location in locations:
        # Generate a random date/time over the past 24 hours
        time = datetime.now() - timedelta(hours=random.randint(0, 24))

        # Generate random weather data
        temperature = random.uniform(-10.0, 40.0)  # temperature in Celsius
        humidity = random.uniform(0.0, 100.0)  # relative humidity in percent
        pressure = random.uniform(950.0, 1050.0)  # atmospheric pressure in hPa

        # Add this metadata to the dictionary
        metadata[location["name"]] = {
            "name": location["name"],
            "lat": location["lat"],
            "lon": location["lon"],
            "time": time.isoformat(),
            "temperature": round(temperature, 2),
            "humidity": round(humidity, 2),
            "pressure": round(pressure, 2),
        }
    return metadata


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
        hasher.update(self.location.encode("utf-8"))
        hash_val = int(hasher.hexdigest(), 16)

        # Reduce the hash value modulo 2^32 to create a valid seed
        seed = hash_val % (2**32)

        # Use the seed to seed the random number generator
        random.seed(seed)
        np.random.seed(seed)

    def build_graph(self):
        for i in range(self.num_nodes):
            node_id = f"{self.location}_species{i + 1}"
            node_label = f"Species {i + 1}"
            node_href = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text=Species{i + 1}"
            num_edges = random.randint(1, 3) if i < self.num_nodes - 2 else random.randint(8, 12)
            self.nodes.append(
                {
                    "data": {
                        "id": node_id,
                        "label": node_label,
                        "href": node_href,
                        "num_edges": num_edges,
                    }
                }
            )

        # Sort nodes by num_edges in descending order
        self.nodes.sort(key=lambda x: x["data"]["num_edges"], reverse=True)

        # Create a set for holding existing edges (to prevent duplicate edges)
        existing_edges = set()

        for source_node in self.nodes:
            source_node_id = source_node["data"]["id"]
            num_source_edges = source_node["data"]["num_edges"]

            while num_source_edges > 0:
                available_targets = [
                    node
                    for node in self.nodes
                    if node["data"]["id"] != source_node_id
                    and node["data"]["num_edges"] > 0
                    and (source_node_id, node["data"]["id"]) not in existing_edges
                ]
                if not available_targets:
                    break

                target_node = random.choice(available_targets)
                target_node_id = target_node["data"]["id"]
                edge_id = f"{self.location}_edge{len(self.edges) + 1}"
                intensity = random.uniform(0.1, 1.0)
                edge_image = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text={source_node_id}-{target_node_id}"
                self.edges.append(
                    {
                        "data": {
                            "id": edge_id,
                            "source": source_node_id,
                            "target": target_node_id,
                            "image": edge_image,
                            "intensity": intensity,
                        }
                    }
                )

                # Decrease num_edges of both source and target nodes
                source_node["data"]["num_edges"] -= 1
                target_node["data"]["num_edges"] -= 1

                # Add this edge to the existing_edges set
                existing_edges.add((source_node_id, target_node_id))


# location1 = Graph(20, "location1")
# location2 = Graph(20, "location2")
