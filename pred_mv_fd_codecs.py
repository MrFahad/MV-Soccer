import torch
import cv2
import numpy as np
import ffmpeg
from ultralytics.yolo.engine.results import Results
from ultralytics.yolo.utils import DEFAULT_CFG, ROOT, ops
from ultralytics.yolo.v8.detect.predict import DetectionPredictor

def estimate_player_positions(boxes, frame_width, frame_height):
    
    player_positions = []

    for box in boxes:
        x1, y1, x2, y2 = box

        # Ensure the bounding box coordinates are within the frame dimensions
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(frame_width, x2), min(frame_height, y2)

        # Calculate the center of the bounding box
        center_x = int(x1 + 0.5 * (x2 - x1))
        center_y = int(y1 + 0.5 * (y2 - y1))

        player_positions.append((center_x, center_y))

    return player_positions

class CustomResults(Results):
    def __init__(self, orig_img, path, names, boxes, masks=None, player_positions=None):
        super().__init__(orig_img=orig_img, path=path, names=names, boxes=boxes, masks=masks)
        self.player_positions = player_positions

class SegmentationPredictor(DetectionPredictor):
    def __init__(self, cfg=DEFAULT_CFG, overrides=None, _callbacks=None):
        super().__init__(cfg, overrides, _callbacks)
        self.args.task = 'segment'

    def postprocess(self, preds, img, orig_imgs):
        p = ops.non_max_suppression(preds[0],
                                    self.args.conf,
                                    self.args.iou,
                                    agnostic=self.args.agnostic_nms,
                                    max_det=self.args.max_det,
                                    nc=len(self.model.names),
                                    classes=self.args.classes)
        results = []
        proto = preds[1][-1] if len(preds[1]) == 3 else preds[1]

        for i, pred in enumerate(p):
            orig_img = orig_imgs[i] if isinstance(orig_imgs, list) else orig_imgs
            path = self.batch[0]
            img_path = path[i] if isinstance(path, list) else path
            if not len(pred):
                results.append(CustomResults(orig_img=orig_img, path=img_path, names=self.model.names, boxes=pred[:, :6]))
                continue

            if i > 0:
                prev_img = orig_imgs[i - 1]
                flow = compute_optical_flow(prev_img, orig_img)
                pred[:, :4] += torch.tensor([flow[x, y] for x, y, _, _ in pred]).to(pred.device)

            if i > 0:
                diff_img = compute_frame_difference(orig_img, orig_imgs[i - 1])
                if np.sum(diff_img) < threshold:
                    continue

            if self.args.retina_masks:
                if not isinstance(orig_imgs, torch.Tensor):
                    pred[:, :4] = ops.scale_boxes(img.shape[2:], pred[:, :4], orig_img.shape)
                masks = ops.process_mask_native(proto[i], pred[:, 6:], pred[:, :4], orig_img.shape[:2])  # HWC
            else:
                masks = ops.process_mask(proto[i], pred[:, 6:], pred[:, :4], img.shape[2:], upsample=True)  # HWC
                if not isinstance(orig_imgs, torch.Tensor):
                    pred[:, :4] = ops.scale_boxes(img.shape[2:], pred[:, :4], orig_img.shape)

            # Call player position estimation
            player_positions = estimate_player_positions(pred[:, :4].cpu().numpy(), orig_img.shape[1], orig_img.shape[0])

            results.append(
                CustomResults(orig_img=orig_img, path=img_path, names=self.model.names, boxes=pred[:, :6], masks=masks,
                              player_positions=player_positions))
        return results

def compute_optical_flow(prev_frame, curr_frame):
    # Convert frames to grayscale
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

    # Compute optical flow using DenseNet method
    optical_flow = cv2.optflow.createOptFlow_DenseNet()
    flow = optical_flow.calc(prev_gray, curr_gray, None)

    return flow

def compute_frame_difference(frame1, frame2):
    # Compute absolute difference between frames
    diff = cv2.absdiff(frame1, frame2)

    # Convert to grayscale
    gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    # Apply thresholding to highlight significant differences
    _, threshold = cv2.threshold(gray_diff, 30, 255, cv2.THRESH_BINARY)

    return threshold

def encode_video(frames, output_file, codec='h264', fps=16):
    height, width, _ = frames[0].shape
    fourcc = cv2.VideoWriter_fourcc(*codec)
    video_writer = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

    for frame in frames:
        video_writer.write(frame)

    video_writer.release()

def decode_video(input_file):
    ffmpeg.input(input_file).output('o1.mp4').run()

def predict(cfg=DEFAULT_CFG, use_python=False):
    """Runs YOLO object detection on an image or video source."""
    model = cfg.model or 'mv-soccer.pt'
    source = cfg.source if cfg.source is not None else ROOT / 'abc' if (ROOT / 'abc').exists() \
    else 'video/1.mp4'

    args = dict(model=model, source=source)
    if use_python:
        from ultralytics import YOLO
        YOLO(model)(**args)
    else:
        predictor = SegmentationPredictor(overrides=args)
        predictor.predict_cli()

if __name__ == '__main__':
    predict()
    
    
    
    
  
    
    
    
    