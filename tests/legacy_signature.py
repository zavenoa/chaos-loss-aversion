"""Original z.1.0 signature() kept verbatim as a test oracle."""
import numpy as np

def signature(neg, pos):
    # Sample high-contrast, spatially distributed RGB pixels, rejecting edges/hover noise.
    if neg.shape != pos.shape: raise ValueError('Calibration images have different dimensions')
    h,w=neg.shape[:2]
    a=neg.astype(np.int16); b=pos.astype(np.int16)
    diff=np.max(np.abs(a-b),axis=2)
    # Use only the lower horizontal border and lower sections of the vertical
    # borders. Hovering a Chaos Orb can obscure the top half with its tooltip.
    yy,xx=np.indices((h,w))
    band=max(3,min(h,w)//9)
    lower=yy>=int(h*0.55)
    mask=lower & ((xx<band)|(xx>=w-band)|(yy>=h-band))
    mask[:2,:]=False; mask[-2:,:]=False; mask[:,:2]=False; mask[:,-2:]=False
    ranked=np.argsort(np.where(mask,diff,-1).ravel())[::-1]
    picks=[]; spacing=max(3,min(h,w)//24)
    for idx in ranked:
        y,x=divmod(int(idx),w)
        if diff[y,x]<35: break
        if all((x-px)**2+(y-py)**2>=spacing**2 for px,py in picks): picks.append((x,y))
        if len(picks)>=24: break
    if len(picks)<4: raise ValueError('Insufficient LOWER border contrast. Ensure the lower gold border is visible in the positive calibration and recapture.')
    return {'points':picks,'negative':[neg[y,x].tolist() for x,y in picks],
            'positive':[pos[y,x].tolist() for x,y in picks], 'threshold':36, 'region':'lower-border-v2'}

