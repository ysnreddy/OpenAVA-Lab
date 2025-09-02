# save as export_cvat_xml.py

import psycopg2
import xml.etree.ElementTree as ET

def export_to_xml(db_params, output_file):
    conn = psycopg2.connect(**db_params)
    cur = conn.cursor()

    query = """
    SELECT t.name as task_name, a.track_id, a.frame, a.xtl, a.ytl, a.xbr, a.ybr, a.attributes
    FROM annotations a
    JOIN tasks t ON a.task_id = t.task_id
    WHERE t.qc_status = 'approved';
    """
    cur.execute(query)
    rows = cur.fetchall()

    # XML root
    annotations = ET.Element("annotations")

    for task_name, track_id, frame, xtl, ytl, xbr, ybr, attributes in rows:
        image = ET.SubElement(annotations, "image", id=str(frame), name=f"{task_name}_{frame}.jpg")

        box = ET.SubElement(image, "box", {
            "label": "person",
            "occluded": "0",
            "source": "manual",
            "xtl": str(xtl),
            "ytl": str(ytl),
            "xbr": str(xbr),
            "ybr": str(ybr)
        })

        if attributes:
            for key, value in attributes.items():
                attr = ET.SubElement(box, "attribute", name=key)
                attr.text = value

    # Write to file
    tree = ET.ElementTree(annotations)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)

    cur.close()
    conn.close()
    print(f"✅ Exported annotations to {output_file}")


if __name__ == "__main__":
    db_params = {
        "dbname": "cvat_annotations_db",
        "user": "admin",
        "password": "admin",
        "host": "127.0.0.1",
        "port": "55432"
    }
    export_to_xml(db_params, "approved_annotations.xml")
