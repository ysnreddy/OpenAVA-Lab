import xml.etree.ElementTree as ET
import pandas as pd

def parse_cvat_xml(xml_file, output_csv):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    rows = []

    for image in root.findall("image"):
        video_id = image.attrib.get("id")
        frame_timestamp = image.attrib.get("name")  # filename is treated as timestamp

        for box in image.findall("box"):
            label = box.attrib.get("label")
            xtl = float(box.attrib.get("xtl"))
            ytl = float(box.attrib.get("ytl"))
            xbr = float(box.attrib.get("xbr"))
            ybr = float(box.attrib.get("ybr"))

            rows.append({
                "video_id": video_id,
                "frame_timestamp": frame_timestamp,
                "x1": xtl,
                "y1": ytl,
                "x2": xbr,
                "y2": ybr,
                "action_id": label,   # using label as action_id
                "person_id": None     # if you have person_id, replace accordingly
            })

    df = pd.DataFrame(rows)

    if df.empty:
        print("⚠️ No bounding boxes found in the XML!")
    else:
        df.to_csv(output_csv, index=False)
        print(f"✅ Saved {len(df)} annotations to {output_csv}")


if __name__ == "__main__":
    parse_cvat_xml("approved_annotations.xml", "annotations.csv")
