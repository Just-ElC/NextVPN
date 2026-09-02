using System.Numerics;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Hosting;
using NextVpn.Core;

namespace NextVpn.Views;

/// <summary>
/// Motion for the connect control.
///
/// Everything here runs as a composition animation, which is evaluated on the
/// compositor thread rather than per-frame on the UI thread. Nothing in this class
/// allocates while an animation is running: the animation objects are built once and
/// restarted, so a tunnel that stays connected for hours costs nothing.
/// </summary>
public sealed class ConnectAnimator : IDisposable
{
    private readonly FrameworkElement _ripple1;
    private readonly FrameworkElement _ripple2;
    private readonly FrameworkElement _arc;
    private readonly FrameworkElement _glow;
    private readonly FrameworkElement _button;

    private readonly Visual _ripple1Visual;
    private readonly Visual _ripple2Visual;
    private readonly Visual _arcVisual;
    private readonly Visual _glowVisual;
    private readonly Visual _buttonVisual;
    private readonly Compositor _compositor;

    // Built once, restarted as needed.
    private readonly Vector3KeyFrameAnimation _rippleScale;
    private readonly ScalarKeyFrameAnimation _rippleFade;
    private readonly ScalarKeyFrameAnimation _arcSpin;
    private readonly ScalarKeyFrameAnimation _fade;
    private readonly SpringVector3NaturalMotionAnimation _buttonSpring;

    private TunnelState _state = TunnelState.Disconnected;
    private bool _busyRunning;
    private bool _pointerOver;
    private bool _disposed;

    /// <summary>Glow strength per state. Idle is a hint, connected is a statement.</summary>
    private const float GlowIdle = 0.30f;
    private const float GlowBusy = 0.55f;
    private const float GlowConnected = 1.0f;

    public ConnectAnimator(FrameworkElement ripple1, FrameworkElement ripple2, FrameworkElement arc,
                           FrameworkElement glow, FrameworkElement button)
    {
        _ripple1 = ripple1;
        _ripple2 = ripple2;
        _arc = arc;
        _glow = glow;
        _button = button;

        _ripple1Visual = ElementCompositionPreview.GetElementVisual(ripple1);
        _ripple2Visual = ElementCompositionPreview.GetElementVisual(ripple2);
        _arcVisual = ElementCompositionPreview.GetElementVisual(arc);
        _glowVisual = ElementCompositionPreview.GetElementVisual(glow);
        _buttonVisual = ElementCompositionPreview.GetElementVisual(button);
        _compositor = _buttonVisual.Compositor;

        var easeOut = _compositor.CreateCubicBezierEasingFunction(
            new Vector2(0.16f, 1.0f), new Vector2(0.30f, 1.0f));
        var linear = _compositor.CreateLinearEasingFunction();

        // Expanding ring: starts just inside the button, grows past the glow.
        _rippleScale = _compositor.CreateVector3KeyFrameAnimation();
        _rippleScale.InsertKeyFrame(0.0f, new Vector3(0.62f, 0.62f, 1f));
        _rippleScale.InsertKeyFrame(1.0f, new Vector3(1.10f, 1.10f, 1f), easeOut);
        _rippleScale.Duration = TimeSpan.FromSeconds(2.4);
        _rippleScale.IterationBehavior = AnimationIterationBehavior.Forever;

        _rippleFade = _compositor.CreateScalarKeyFrameAnimation();
        _rippleFade.InsertKeyFrame(0.0f, 0.0f);
        _rippleFade.InsertKeyFrame(0.18f, 0.62f);
        _rippleFade.InsertKeyFrame(1.0f, 0.0f, easeOut);
        _rippleFade.Duration = TimeSpan.FromSeconds(2.4);
        _rippleFade.IterationBehavior = AnimationIterationBehavior.Forever;

        // One turn of the arc, at a constant speed. Rotation is a compositor
        // property, so this costs nothing on the UI thread no matter how long a
        // connection attempt takes.
        _arcSpin = _compositor.CreateScalarKeyFrameAnimation();
        _arcSpin.InsertKeyFrame(0.0f, 0.0f);
        _arcSpin.InsertKeyFrame(1.0f, 360.0f, linear);
        _arcSpin.Duration = TimeSpan.FromSeconds(1.9);
        _arcSpin.IterationBehavior = AnimationIterationBehavior.Forever;

        // Shared fade, retargeted per call rather than one animation per state.
        _fade = _compositor.CreateScalarKeyFrameAnimation();
        _fade.Duration = TimeSpan.FromMilliseconds(320);

        _buttonSpring = _compositor.CreateSpringVector3Animation();
        _buttonSpring.DampingRatio = 0.45f;
        _buttonSpring.Period = TimeSpan.FromMilliseconds(50);

        ripple1.SizeChanged += OnSizeChanged;
        ripple2.SizeChanged += OnSizeChanged;
        arc.SizeChanged += OnSizeChanged;
        glow.SizeChanged += OnSizeChanged;
        button.SizeChanged += OnSizeChanged;
        Recentre();

        HookPointer();

        _glowVisual.Opacity = GlowIdle;
    }

    private void OnSizeChanged(object sender, SizeChangedEventArgs e) => Recentre();

    /// <summary>Scale and rotation have to pivot on the middle of each circle, not its corner.</summary>
    private void Recentre()
    {
        _ripple1Visual.CenterPoint = Centre(_ripple1);
        _ripple2Visual.CenterPoint = Centre(_ripple2);
        _arcVisual.CenterPoint = Centre(_arc);
        _glowVisual.CenterPoint = Centre(_glow);
        _buttonVisual.CenterPoint = Centre(_button);

        static Vector3 Centre(FrameworkElement e) =>
            new((float)e.ActualWidth / 2f, (float)e.ActualHeight / 2f, 0f);
    }

    // ------------------------------------------------------------------ state

    public void SetState(TunnelState state)
    {
        if (_disposed) return;

        var previous = _state;
        _state = state;

        switch (state)
        {
            case TunnelState.Connecting:
            case TunnelState.Disconnecting:
                StartBusy();
                FadeGlow(GlowBusy);
                break;

            case TunnelState.Connected:
                // Deliberately static once up. A permanently breathing glow forces the
                // compositor to redraw the whole window - mica included - forever,
                // which costs real CPU and battery for no information. Motion is
                // reserved for transitions and for "something is happening".
                StopBusy();
                FadeGlow(GlowConnected);
                if (previous != TunnelState.Connected) Pop(1.06f);
                break;

            default:
                StopBusy();
                FadeGlow(GlowIdle);
                if (previous == TunnelState.Connected) Pop(0.94f);
                break;
        }
    }

    private void FadeGlow(float target)
    {
        _fade.InsertKeyFrame(1.0f, target);
        _glowVisual.StartAnimation("Opacity", _fade);
    }

    private void StartBusy()
    {
        if (_busyRunning) return;
        _busyRunning = true;

        // The rings are never collapsed, only faded. Changing Visibility makes XAML
        // push the element's own Opacity back onto the visual on the next layout
        // pass, which silently cancels the composition animation started here - the
        // rings were declared visible and then never appeared.

        // The second ring is offset by half a cycle so the pulse reads as continuous.
        _rippleScale.DelayTime = TimeSpan.Zero;
        _rippleFade.DelayTime = TimeSpan.Zero;
        _ripple1Visual.StartAnimation("Scale", _rippleScale);
        _ripple1Visual.StartAnimation("Opacity", _rippleFade);

        _rippleScale.DelayTime = TimeSpan.FromSeconds(1.2);
        _rippleFade.DelayTime = TimeSpan.FromSeconds(1.2);
        _ripple2Visual.StartAnimation("Scale", _rippleScale);
        _ripple2Visual.StartAnimation("Opacity", _rippleFade);

        _arcVisual.StartAnimation("RotationAngleInDegrees", _arcSpin);

        _fade.InsertKeyFrame(1.0f, 1.0f);
        _arcVisual.StartAnimation("Opacity", _fade);
    }

    private void StopBusy()
    {
        if (!_busyRunning) return;
        _busyRunning = false;

        _ripple1Visual.StopAnimation("Scale");
        _ripple1Visual.StopAnimation("Opacity");
        _ripple2Visual.StopAnimation("Scale");
        _ripple2Visual.StopAnimation("Opacity");
        _arcVisual.StopAnimation("RotationAngleInDegrees");
        _arcVisual.StopAnimation("Opacity");

        _ripple1Visual.Opacity = 0f;
        _ripple2Visual.Opacity = 0f;
        _arcVisual.Opacity = 0f;
        _arcVisual.RotationAngleInDegrees = 0f;
    }

    /// <summary>A short spring overshoot, so connecting and disconnecting feel physical.</summary>
    private void Pop(float peak)
    {
        _buttonSpring.InitialValue = new Vector3(peak, peak, 1f);
        _buttonSpring.FinalValue = RestingScale;
        _buttonVisual.StartAnimation("Scale", _buttonSpring);
    }

    // ---------------------------------------------------------------- pointer

    private Vector3 RestingScale => _pointerOver ? new Vector3(1.04f, 1.04f, 1f) : Vector3.One;

    private void HookPointer()
    {
        _button.PointerEntered += (_, _) => { _pointerOver = true; ScaleTo(1.04f); };
        _button.PointerExited += (_, _) => { _pointerOver = false; ScaleTo(1.0f); };
        _button.PointerCanceled += (_, _) => { _pointerOver = false; ScaleTo(1.0f); };

        // Press pulls the control in slightly; release returns it to whatever the
        // pointer is doing now, rather than assuming it is still over the button.
        _button.PointerPressed += (_, _) => ScaleTo(0.955f);
        _button.PointerReleased += (_, _) => ScaleTo(RestingScale.X);
        _button.PointerCaptureLost += (_, _) => ScaleTo(RestingScale.X);
    }

    private void ScaleTo(float target)
    {
        if (_disposed) return;
        _buttonSpring.InitialValue = _buttonVisual.Scale;
        _buttonSpring.FinalValue = new Vector3(target, target, 1f);
        _buttonVisual.StartAnimation("Scale", _buttonSpring);
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        StopBusy();
        _glowVisual.StopAnimation("Opacity");
        _buttonVisual.StopAnimation("Scale");

        _ripple1.SizeChanged -= OnSizeChanged;
        _ripple2.SizeChanged -= OnSizeChanged;
        _arc.SizeChanged -= OnSizeChanged;
        _glow.SizeChanged -= OnSizeChanged;
        _button.SizeChanged -= OnSizeChanged;
    }
}
