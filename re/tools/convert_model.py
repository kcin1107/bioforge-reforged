"""Converts the 4x model used for High-Resolution Art to Core ML, for the app to build the art pack itself (PixelPack.swift).

    <venv with torch, spandrel, coremltools>/bin/python -I re/tools/convert_model.py 4x_HDCube_200k.pth OUT_DIR

Writes OUT_DIR/HDCube.mlmodelc (compiled with xcrun coremlcompiler). Input "image": 1x3xHxW float RGB in 0..1, the 70 sizes of
PixelPackBuilder.bucket: H 32, 64, ..., 192, 200 by W 32, 64, ..., 320 (a room crop or a texture, padded to one);
output "upscaled": 1x3x4Hx4W. Weights are stored as fp16.
"""
import os, shutil, subprocess, sys, tempfile


def main():
    if len(sys.argv) != 3: sys.exit(__doc__)
    import coremltools as ct, torch
    from spandrel import ModelLoader                    # loads .pth files through a restricted unpickler
    model = ModelLoader().load_from_file(sys.argv[1])
    if model.scale != 4: sys.exit('need a 4x model')
    net = model.model.eval().float()
    traced = torch.jit.trace(net, torch.rand(1, 3, 64, 64))
    sizes = [(1, 3, h, w) for h in [*range(32, 200, 32), 200] for w in range(32, 321, 32)]
    shape = ct.EnumeratedShapes(shapes=sizes, default=(1, 3, 64, 64))      # fixed shapes run on the Neural Engine
    ml = ct.convert(traced, inputs=[ct.TensorType(name='image', shape=shape)], outputs=[ct.TensorType(name='upscaled')],
                    convert_to='mlprogram', compute_precision=ct.precision.FLOAT16, minimum_deployment_target=ct.target.macOS14)
    ml.short_description = '4x_HDCube_200k (github.com/Venomalia/HDcube): the guide for High-Resolution Art'
    os.makedirs(sys.argv[2], exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, 'HDCube.mlpackage')
        ml.save(pkg)
        out = os.path.join(sys.argv[2], 'HDCube.mlmodelc')
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run(['xcrun', 'coremlcompiler', 'compile', pkg, sys.argv[2]], check=True, stdout=subprocess.DEVNULL)
    print(out)


if __name__ == '__main__':
    main()
