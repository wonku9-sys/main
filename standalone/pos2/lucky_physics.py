"""Display-only ball motion. Never used to choose lottery result numbers."""
from dataclasses import dataclass
import math
import random

@dataclass(slots=True)
class Ball:
    number:int
    x:float
    y:float
    vx:float=0
    vy:float=0
    angle:float=0
    spin:float=0

class BallMotion:
    radius=103.0
    ball_radius=8.6

    def __init__(self,seed=None):
        self.random=random.Random(seed);self.time=0;self.mixing=False
        numbers=list(range(1,46));self.random.shuffle(numbers);self.balls=[]
        limit=self.radius-self.ball_radius-1
        y=limit-2
        while len(self.balls)<45:
            span=math.sqrt(max(0,limit*limit-y*y));spacing=self.ball_radius*2+.5
            count=max(1,int(span*2/spacing))
            for i in range(count):
                if len(self.balls)==45:break
                x=(i-(count-1)/2)*spacing
                self.balls.append(Ball(numbers[len(self.balls)],x,y,angle=self.random.uniform(-20,20)))
            y-=spacing

    def advance(self,seconds,mixing):
        if not math.isfinite(seconds) or seconds<0:raise ValueError('공 움직임 시간은 유한한 양수여야 합니다.')
        seconds=min(seconds,.05)
        if not seconds:return
        if mixing and not self.mixing:
            for ball in self.balls:
                ball.vx+=self.random.uniform(-105,105);ball.vy-=self.random.uniform(130,255);ball.spin=self.random.uniform(-180,180)
        self.mixing=bool(mixing)
        steps=max(1,math.ceil(seconds/(1/120)));dt=seconds/steps
        for _ in range(steps):self._step(dt)

    def _wall(self,ball):
        limit=self.radius-self.ball_radius;distance=math.hypot(ball.x,ball.y)
        if distance<=limit:return
        nx,ny=ball.x/distance,ball.y/distance;ball.x,ball.y=nx*limit,ny*limit
        outward=ball.vx*nx+ball.vy*ny
        if outward>0:
            bounce=.82 if self.mixing else .36
            ball.vx-=(1+bounce)*outward*nx;ball.vy-=(1+bounce)*outward*ny
            ball.vx*=.98;ball.spin+=(ball.vx*ny-ball.vy*nx)*.18

    def _step(self,dt):
        self.time+=dt;drag=math.exp(-(.25 if self.mixing else 1.8)*dt)
        for b in self.balls:
            ax=0;ay=215.0
            if self.mixing:
                # Air rises near the lower centre; the sides return balls down.
                jet=max(0,1-abs(b.x)/64)*max(0,(b.y+100)/200)
                ay-=940*jet;ax=math.sin(self.time*4+b.y*.045)*92-b.y*1.35
                ay+=b.x*.55
            b.vx=(b.vx+ax*dt)*drag;b.vy=(b.vy+ay*dt)*drag
            speed=math.hypot(b.vx,b.vy)
            if speed>420:b.vx*=420/speed;b.vy*=420/speed
            b.x+=b.vx*dt;b.y+=b.vy*dt;b.angle=(b.angle+b.spin*dt)%360;b.spin*=drag
            self._wall(b)
        diameter=self.ball_radius*2
        for i,a in enumerate(self.balls):
            for b in self.balls[i+1:]:
                dx,dy=b.x-a.x,b.y-a.y;distance2=dx*dx+dy*dy
                if distance2>=diameter*diameter:continue
                distance=math.sqrt(distance2) if distance2>1e-12 else 1e-6
                nx,ny=(dx/distance,dy/distance) if distance2>1e-12 else (1.0,0.0)
                correction=(diameter-distance)*.5
                a.x-=nx*correction;a.y-=ny*correction;b.x+=nx*correction;b.y+=ny*correction
                approach=(b.vx-a.vx)*nx+(b.vy-a.vy)*ny
                if approach<0:
                    impulse=-(1+(.86 if self.mixing else .25))*approach*.5
                    a.vx-=impulse*nx;a.vy-=impulse*ny;b.vx+=impulse*nx;b.vy+=impulse*ny
                    roll=((b.vx-a.vx)*ny-(b.vy-a.vy)*nx)*.2
                    a.spin+=roll;b.spin-=roll
        for b in self.balls:self._wall(b)
