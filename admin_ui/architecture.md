# Video Processing Pipeline

An asynchronous video processing system built for robustness, scalability, and improved user experience when handling large video files.

## System Architecture

The pre-processing stage is built as a modern web application with clear separation between the user interface (frontend) and processing logic (backend). This architecture is designed for robustness, scalability, and an improved user experience, especially when handling large video files that take a long time to process.

## Core Components

The system consists of three main components that work together:

### Frontend (`frontend.py`)
A user-friendly web interface built with **Streamlit**. Its sole responsibility is to allow an administrator to upload raw video files and monitor the status of their processing jobs.

### Backend (`app.py`) 
A powerful API server built with **FastAPI**. This is the brain of the operation. It does not perform the heavy processing itself. Instead, it acts as a job manager, receiving requests from the frontend and orchestrating the pipeline in the background.

### Processing Tools (`tools/` directory)
A collection of specialized, single-purpose Python scripts. Each script is an expert at one specific task (e.g., resizing videos, extracting frames, running the tracker). The backend calls these tools in the correct sequence to build the final data package.

## The Asynchronous Workflow: Why This is More Efficient

A simple, synchronous script would force the user to wait in their browser for the entire process to finish, which could take hours and would inevitably lead to connection timeouts. Our asynchronous architecture solves this problem and provides several key advantages:

### No Timeouts & Better UX
When a user uploads videos, the backend responds instantly with a `job_id`. The heavy processing then happens in the background. The user can close their browser, and the job will continue to run. They can check the status at any time using their `job_id`.

### Robustness & Error Handling
Each processing job runs in its own isolated, temporary directory. If a job fails, it does not affect the main server or any other running jobs. The temporary files for that specific job are automatically cleaned up, preventing the server from filling up with orphaned data.

### Scalability
This design is built for growth. In a future cloud deployment (e.g., on AWS), we can easily scale the system by adding more processing workers. The FastAPI server would simply distribute the jobs to a queue, and multiple workers could process videos in parallel, dramatically speeding up the workflow.

### Modularity
Each step of the pipeline is a separate script. This makes the system incredibly easy to maintain and upgrade. For example, if we want to swap out the Kalman Filter tracker for a new, state-of-the-art algorithm, we only need to change one line in `app.py` to call a different tool. The rest of the pipeline remains untouched.

## Workflow Overview

This diagram illustrates the entire process from the user's perspective, from uploading a video to downloading the final, processed package.

```
+------------------+      +--------------------+      +------------------+
| 1. User uploads  |----->| Backend instantly  |----->| 2. UI receives a |
|    raw videos    |      | responds with a    |      |    `job_id`      |
+------------------+      |      `job_id`      |      +------------------+
                          +--------------------+
                                                         |
                                                         | (UI periodically checks status via API)
                                                         V
+------------------+      +--------------------+      +------------------+
| 4. User downloads|<-----| Backend reports    |<-----| 3. UI asks, "Is  |
|    final package |      | job is "completed" |      |    job #123 done?"|
+------------------+      +--------------------+      +------------------+
```

### Behind the Scenes (Background Job)

```
[Raw Video] -> [Tool 1: Resize] -> [Tool 2: Clip] -> [Tool 3: Extract Frames] -> [Tool 4: Track Persons] -> [Tool 5: Generate Proposals] -> [Final ZIP Package]
```

## Processing Pipeline

The system processes videos through the following sequential steps:

1. **Tool 1: Resize** - Standardizes video dimensions
2. **Tool 2: Clip** - Segments videos into manageable chunks  
3. **Tool 3: Extract Frames** - Converts video segments to individual frames
4. **Tool 4: Track Persons** - Detects and tracks people across frames
5. **Tool 5: Generate Proposals** - Creates annotation proposals for downstream processing

## Final Output Structure

The ultimate goal of this pipeline is to produce a single, self-contained ZIP archive that is ready for the next stage (upload to the task creation dashboard). The final package has the following structure:

```
final_package.zip
├── dense_proposals.pkl
└── frames/
    ├── 1_clip_000.zip
    ├── 1_clip_001.zip
    └── ...
```

This structure provides both the high-level proposal data and the individually packaged frames required by the annotation workflow, all in a single, convenient file.

## Getting Started

### Prerequisites

- Python 3.8+
- FastAPI
- Streamlit
- Additional dependencies for video processing (see `requirements.txt`)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd video-processing-pipeline

# Install dependencies
pip install -r requirements.txt
```

### Running the System

1. **Start the backend server:**
   ```bash
   python app.py
   ```

2. **Start the frontend interface:**
   ```bash
   streamlit run frontend.py
   ```

3. **Access the web interface** at the URL provided by Streamlit (typically `http://localhost:8501`)

## Usage

1. Upload raw video files through the Streamlit interface
2. Receive a `job_id` for tracking your processing job
3. Monitor job status in real-time through the UI
4. Download the final processed package when complete

## Project Structure

```
video-processing-pipeline/
├── app.py              # FastAPI backend server
├── frontend.py         # Streamlit frontend interface
├── tools/              # Processing scripts directory
│   ├── resize_tool.py
│   ├── clip_tool.py
│   ├── extract_frames_tool.py
│   ├── track_persons_tool.py
│   └── generate_proposals_tool.py
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## Key Features

- **Asynchronous Processing**: Non-blocking job execution
- **Real-time Status Updates**: Monitor progress without page refreshes
- **Error Isolation**: Failed jobs don't affect other operations
- **Automatic Cleanup**: Temporary files managed automatically  
- **Modular Design**: Easy to modify or extend individual processing steps
- **Self-contained Output**: Complete packages ready for downstream workflows