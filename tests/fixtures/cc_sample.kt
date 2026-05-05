fun base() = 1

fun withWhen(x: Int) {
    when (x) {
        1 -> println("a")
        2 -> println("b")
        else -> println("c")
    }
}
